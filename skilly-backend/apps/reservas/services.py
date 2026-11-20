"""
Lógica de reservas: cálculo de disponibilidad y máquina de estados.

Ticket 3.1 (slots) y 3.2 (máquina de estados). Toda transición de estado pasa
por acá y deja un `EventoReserva`, para que la bitácora sea consistente sin
importar quién dispare la acción (API, admin o un comando).

Regla de bloqueo (R11): una reserva vigente bloquea los slots dentro de las
`HORAS_BLOQUEO_RESERVA` horas siguientes a su inicio. Reservar a las 16:00 con
un colchón de 3 h deja libres recién desde las 19:00.
"""
import logging
from datetime import datetime, timedelta, time as _time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.catalogo.models import Servicio
from apps.comisiones.services import tasa_efectiva
from apps.pagos import estados as pagos_estados
from apps.pagos import services as pagos_services
from apps.pagos.gateway.base import ErrorPasarela
from apps.pagos.models import Pago
from apps.usuarios.correo import enviar_cuenta_creada, enviar_reserva_registrada
from apps.usuarios.models import (
    Horario,
    Organizacion,
    Profesional,
    normalizar_rut,
    validar_rut,
)

from .models import Disputa, EvidenciaDisputa, EventoReserva, Reserva

Usuario = get_user_model()
ZONA = timezone.get_current_timezone()
logger = logging.getLogger(__name__)


# Utilidades de tiempo
def aware(fecha, hora):
    """Combina fecha y hora locales (America/Santiago) en un datetime aware."""
    return timezone.make_aware(datetime.combine(fecha, hora), ZONA)


def plazo_respuesta(reserva, ahora=None):
    """Fecha límite del profesional, sin pasar del margen previo al servicio."""
    ahora = ahora or timezone.now()
    vencimiento = ahora + timedelta(hours=settings.PLAZO_RESPUESTA_PROFESIONAL_HORAS)
    inicio = aware(reserva.fecha, reserva.hora_inicio)
    tope = inicio - timedelta(hours=settings.HORAS_MARGEN_RESPUESTA)
    return min(vencimiento, tope)


def _ventana_bloqueo(reserva):
    """Ventana [inicio, fin) que ocupa una reserva, usando su snapshot."""
    inicio = aware(reserva.fecha, reserva.hora_inicio)
    fin = aware(reserva.fecha, reserva.hora_fin)
    if fin <= inicio:
        # El colchón cruzó la medianoche.
        fin += timedelta(days=1)
    return inicio, fin


def _slots_base(servicio, fecha):
    """Genera los inicios de slot según el horario del profesional."""
    bloques = Horario.objects.filter(
        profesional=servicio.profesional,
        dia_semana=fecha.weekday(),
        activo=True,
    )
    paso = timedelta(minutes=settings.SLOT_MINUTOS)
    for bloque in bloques:
        cursor = aware(fecha, bloque.hora_inicio)
        fin_bloque = aware(fecha, bloque.hora_fin)
        while cursor + paso <= fin_bloque:
            yield cursor, cursor + paso
            cursor += paso


def calcular_slots(servicio, fecha):
    """Devuelve los slots de un día con su disponibilidad.

    Cada elemento es {"hora_inicio", "hora_fin", "disponible"}. Se marca no
    disponible el slot si ya pasó o si cae dentro de la ventana bloqueada de
    una reserva vigente del profesional.
    """
    paso = timedelta(minutes=settings.SLOT_MINUTOS)
    reservas = Reserva.objects.filter(
        profesional=servicio.profesional,
        estado__in=Reserva.ESTADOS_VIGENTES,
        fecha__in=[fecha, fecha - timedelta(days=1)],
    )
    ventanas = [_ventana_bloqueo(r) for r in reservas]
    ahora = timezone.now()

    resultado = []
    for inicio, fin in _slots_base(servicio, fecha):
        disponible = inicio > ahora
        if disponible:
            for v_inicio, v_fin in ventanas:
                if inicio < v_fin and fin > v_inicio:
                    disponible = False
                    break
        resultado.append(
            {"hora_inicio": inicio, "hora_fin": fin, "disponible": disponible}
        )
    return resultado


def dias_disponibles(servicio, desde, dias=45):
    """Resumen por día para el calendario: cuántos slots libres hay."""
    salida = []
    for i in range(dias):
        fecha = desde + timedelta(days=i)
        libres = sum(1 for s in calcular_slots(servicio, fecha) if s["disponible"])
        salida.append({"fecha": fecha, "libres": libres})
    return salida


# Creación de la reserva (ticket 3.5)
def _crear_usuario_invitado(datos):
    """Crea la cuenta automática de una reserva sin registro.

    Nace con contraseña inutilizable: el invitado la define al activar la
    cuenta desde el correo. Ver decisión de la Iteración 3 sobre reserva de invitado.
    """
    nombre = (datos.get("nombre") or "").strip()
    partes = nombre.split(" ")
    email_norm = Usuario.objects.normalize_email(datos["email"]).lower()
    usuario = Usuario(
        email=email_norm,
        first_name=partes[0][:150] if partes else "",
        last_name=" ".join(partes[1:])[:150] if len(partes) > 1 else "",
        tipo=Usuario.TIPO_ORGANIZACION,
        is_active=True,
    )
    usuario.set_unusable_password()
    usuario.save()
    return usuario


def _rut_limpio(datos):
    """Devuelve el RUT normalizado si es válido, o None si falta o no sirve."""
    rut = (datos.get("rut") or "").strip()
    if not rut:
        return None
    try:
        validar_rut(rut)
    except ValueError:
        return None
    return normalizar_rut(rut)


def _crear_organizacion_invitada(datos, usuario):
    rut_limpio = _rut_limpio(datos)
    if rut_limpio and Organizacion.objects.filter(rut=rut_limpio).exists():
        rut_limpio = None
    return Organizacion.objects.create(
        nombre=datos.get("empresa") or datos.get("nombre") or "Organización invitada",
        nombre_contacto=datos.get("nombre") or "Contacto invitado",
        email_contacto=datos["email"],
        telefono=datos.get("telefono", ""),
        rut=rut_limpio,
        modo=Organizacion.MODO_INVITADA,
        usuario=usuario,
    )


def _resolver_organizacion(organizacion, creada_por, datos):
    """Decide a qué organización pertenece la reserva y arma su cuenta.

    Devuelve `(organizacion, aviso)` donde `aviso` es:
      - "cuenta_nueva": se creó una cuenta; hay que enviar el correo de
        activación para que el invitado defina su contraseña.
      - "existente": el correo ya tenía cuenta; se enlaza la reserva a su
        organización y se avisa por correo.
      - None: reserva autenticada (o sin cuenta asociable): sin correo.

    Una reserva sin sesión solo puede reutilizar cuentas invitadas que aún no
    tienen contraseña usable. Si el correo o el RUT apuntan a una cuenta
    registrada se rechaza: enlazarla sin verificación permitiría a un tercero
    reservar a nombre de esa organización.
    """
    if organizacion is not None:
        return organizacion, None
    if creada_por is not None:
        return getattr(creada_por, "organizacion", None), None

    email = Usuario.objects.normalize_email(datos["email"]).lower()
    usuario = Usuario.objects.filter(email__iexact=email).first()

    if usuario is not None:
        if usuario.tipo == Usuario.TIPO_ORGANIZACION:
            if usuario.has_usable_password():
                raise ValidationError(
                    "Ese correo ya tiene una cuenta. Inicia sesión para reservar."
                )
            existente = getattr(usuario, "organizacion", None)
            if existente is not None:
                return existente, {"cuenta": "existente", "usuario": usuario}

            rut_limpio = _rut_limpio(datos)
            if rut_limpio:
                existente_rut = Organizacion.objects.filter(rut=rut_limpio).first()
                if existente_rut is not None:
                    if (
                        existente_rut.usuario_id is not None
                        and existente_rut.usuario_id != usuario.pk
                    ):
                        raise ValidationError(
                            "Ese RUT ya está asociado a otra cuenta. Revisa tus datos."
                        )
                    existente_rut.usuario = usuario
                    existente_rut.modo = Organizacion.MODO_INVITADA
                    existente_rut.save(update_fields=["usuario", "modo"])
                    return existente_rut, {"cuenta": "existente", "usuario": usuario}
            organizacion = _crear_organizacion_invitada(datos, usuario)
            return organizacion, {"cuenta": "existente", "usuario": usuario}
        # Profesional o admin: no se le cuelga una organización.
        organizacion = _crear_organizacion_invitada(datos, None)
        return organizacion, {"cuenta": None, "usuario": None}

    rut_limpio = _rut_limpio(datos)
    if rut_limpio:
        existente = Organizacion.objects.filter(rut=rut_limpio).first()
        if existente is not None:
            if existente.usuario_id is not None:
                raise ValidationError(
                    "Ese RUT ya está registrado. Inicia sesión para reservar."
                )
            usuario = _crear_usuario_invitado(datos)
            existente.usuario = usuario
            existente.modo = Organizacion.MODO_INVITADA
            existente.save(update_fields=["usuario", "modo"])
            return existente, {"cuenta": "nueva", "usuario": usuario}

    usuario = _crear_usuario_invitado(datos)
    organizacion = _crear_organizacion_invitada(datos, usuario)
    return organizacion, {"cuenta": "nueva", "usuario": usuario}


def _enlace_activacion(usuario):
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    return f"{base}/activar-cuenta/{uid}/{token}"


@transaction.atomic
def crear_reserva(*, servicio, fecha, hora_inicio, datos, organizacion=None, creada_por=None):
    """Crea una reserva y bloquea el slot. Devuelve (reserva, token).

    `token` es None cuando la reserva la hizo una organización con cuenta y el
    token mágico no hace falta.
    """
    if servicio.estado != Servicio.ESTADO_APROBADO or not servicio.activo:
        raise ValidationError("El servicio no está disponible para reservar.")

    if (
        servicio.precio is None
        or servicio.precio < settings.MONTO_MINIMO_SERVICIO
        or servicio.precio != int(servicio.precio)
    ):
        raise ValidationError(
            "El servicio tiene un precio inválido: debe ser un entero en CLP "
            f"y ser al menos ${settings.MONTO_MINIMO_SERVICIO}."
        )

    if isinstance(hora_inicio, str):
        hora_inicio = _time.fromisoformat(hora_inicio)

    if fecha < timezone.localdate():
        raise ValidationError("No se puede reservar en una fecha pasada.")

    inicio_dt = aware(fecha, hora_inicio)
    if inicio_dt <= timezone.now():
        raise ValidationError("Ese horario ya pasó. Elige otro.")

    Profesional.objects.select_for_update().get(pk=servicio.profesional_id)

    slots = calcular_slots(servicio, fecha)
    disponible = any(
        s["disponible"] and s["hora_inicio"].time() == hora_inicio for s in slots
    )
    if not disponible:
        raise ValidationError("Ese bloque ya no está disponible. Elige otro horario.")

    buffer = timedelta(hours=settings.HORAS_BLOQUEO_RESERVA)
    hora_fin = (inicio_dt + buffer).time()

    organizacion, aviso = _resolver_organizacion(organizacion, creada_por, datos)

    ventana_pago = timedelta(minutes=settings.MINUTOS_PAGO_PENDIENTE)
    reserva = Reserva.objects.create(
        servicio=servicio,
        profesional=servicio.profesional,
        organizacion=organizacion,
        creada_por=creada_por,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        precio_acordado=servicio.precio,
        tasa_comision=tasa_efectiva(servicio.categoria),
        formato=servicio.formato,
        ubicacion=servicio.ubicacion,
        contacto_nombre=datos.get("nombre", ""),
        contacto_email=datos["email"],
        contacto_telefono=datos.get("telefono", ""),
        mensaje=datos.get("mensaje", ""),
        estado=Reserva.ESTADO_PENDIENTE_PAGO,
        expira_en=timezone.now() + ventana_pago,
    )
    EventoReserva.objects.create(
        reserva=reserva,
        tipo=EventoReserva.TIPO_CREADA,
        actor=creada_por,
        detalle="Solicitud de reserva creada; pendiente de pago.",
    )

    if aviso and aviso.get("cuenta") == "nueva":
        usuario = aviso["usuario"]
        enlace = _enlace_activacion(usuario)
        transaction.on_commit(
            lambda: enviar_cuenta_creada(usuario, organizacion, reserva, enlace)
        )
    elif aviso and aviso.get("cuenta") == "existente":
        usuario = aviso["usuario"]
        transaction.on_commit(lambda: enviar_reserva_registrada(usuario, reserva))

    # El invitado (sin sesión) recibe token para ver su reserva de inmediato,
    # incluso si la cuenta ya quedó creada/enlazada.
    token = None
    if creada_por is None:
        token = reserva.generar_token()
    return reserva, token


# Máquina de estados (ticket 3.2)
def _evento(reserva, tipo, actor=None, detalle=""):
    return EventoReserva.objects.create(
        reserva=reserva, tipo=tipo, actor=actor, detalle=detalle
    )


def porcentaje_reembolso(reserva, ahora=None):
    """D3: 100% si se cancela con 24 h o más; si no, el porcentaje tardío."""
    ahora = ahora or timezone.now()
    inicio = aware(reserva.fecha, reserva.hora_inicio)
    horas_restantes = (inicio - ahora).total_seconds() / 3600
    if horas_restantes >= settings.HORAS_CANCELACION_SIN_PENALIDAD:
        return 100
    return settings.PORCENTAJE_REEMBOLSO_CANCELACION_TARDIA


def _pago_activo(reserva):
    """Pago vigente de la reserva, si existe."""
    return pagos_services.pago_vigente(reserva)


def _actor_pago(actor, defecto=Pago.ACTOR_SISTEMA):
    if actor is None:
        return defecto
    if getattr(actor, "es_admin_plataforma", False):
        return Pago.ACTOR_ADMIN
    if getattr(actor, "profesional", None) is not None:
        return Pago.ACTOR_PROFESIONAL
    if getattr(actor, "organizacion", None) is not None:
        return Pago.ACTOR_USUARIO
    return defecto


@transaction.atomic
def activar_tras_pago(reserva, actor=None):
    """Arranca el reloj del profesional cuando el pago quedó confirmado."""
    if reserva.estado != Reserva.ESTADO_PENDIENTE_PAGO:
        return reserva
    reserva.estado = Reserva.ESTADO_PENDIENTE_ACEPTACION
    reserva.expira_en = plazo_respuesta(reserva)
    reserva.save(update_fields=["estado", "expira_en", "actualizada_en"])
    _evento(
        reserva,
        EventoReserva.TIPO_PAGO_CONFIRMADO,
        actor,
        "Pago confirmado; comienza el plazo de respuesta del profesional.",
    )
    return reserva


def aceptar(reserva, actor=None):
    """Acepta la solicitud y captura el pago (tres fases, sin HTTP bloqueado)."""
    original = reserva
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
            raise ValidationError("Esta reserva ya no está pendiente de aceptación.")
        if reserva.expirada:
            raise ValidationError("El plazo para responder esta solicitud venció.")
        pago = _pago_activo(reserva)
        if pago is None:
            raise ValidationError("La reserva no tiene un pago confirmado.")
        if pago.estado not in {pagos_estados.AUTORIZADO, pagos_estados.RETENIDO}:
            raise ValidationError("El pago de esta reserva no está listo para capturar.")

    if pago.estado == pagos_estados.AUTORIZADO:
        pago = pagos_services.capturar_pago(
            pago, actor=_actor_pago(actor, Pago.ACTOR_PROFESIONAL)
        )

    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
            raise ValidationError("Esta reserva ya no está pendiente de aceptación.")
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado != pagos_estados.RETENIDO:
            raise ValidationError("La captura del pago no se completó.")
        reserva.estado = Reserva.ESTADO_EN_CURSO
        reserva.aceptada_en = timezone.now()
        reserva.save(update_fields=["estado", "aceptada_en", "actualizada_en"])
        _evento(
            reserva,
            EventoReserva.TIPO_ACEPTADA,
            actor,
            "El profesional aceptó la solicitud.",
        )
    original.refresh_from_db()
    return original


def rechazar(reserva, actor=None, motivo=""):
    """Rechaza la solicitud revocando o reembolsando el pago."""
    original = reserva
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
            raise ValidationError("Esta reserva ya no está pendiente de aceptación.")
        pago = _pago_activo(reserva)
        accion = _accion_sobre_pago(pago, 100)

    if accion[0] == "cancelar":
        pagos_services.cancelar_pago(
            pago, actor=_actor_pago(actor, Pago.ACTOR_PROFESIONAL)
        )
    elif accion[0] == "reembolsar":
        pagos_services.reembolsar_pago(
            pago,
            porcentaje=accion[1],
            actor=_actor_pago(actor, Pago.ACTOR_PROFESIONAL),
        )

    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
            raise ValidationError("Esta reserva ya no está pendiente de aceptación.")
        reserva.estado = Reserva.ESTADO_CANCELADA
        reserva.motivo_rechazo = (motivo or "").strip()
        reserva.cancelada_por = actor
        reserva.cancelada_en = timezone.now()
        reserva.save(
            update_fields=[
                "estado",
                "motivo_rechazo",
                "cancelada_por",
                "cancelada_en",
                "actualizada_en",
            ]
        )
        _evento(
            reserva,
            EventoReserva.TIPO_RECHAZADA,
            actor,
            reserva.motivo_rechazo or "El profesional rechazó la solicitud.",
        )
    original.refresh_from_db()
    return original


# Entrega marcada por el profesional; queda pendiente de confirmación.
@transaction.atomic
def marcar_entregado(reserva, actor=None):
    if reserva.estado != Reserva.ESTADO_EN_CURSO:
        raise ValidationError("Solo una reserva en curso puede marcarse como entregada.")
    reserva.estado = Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR
    reserva.entregado_en = timezone.now()
    reserva.save(update_fields=["estado", "entregado_en", "actualizada_en"])
    _evento(
        reserva,
        EventoReserva.TIPO_ENTREGADA,
        actor,
        "El profesional marcó el servicio como entregado.",
    )
    return reserva


def _disputa_abierta(reserva):
    """True si la reserva tiene una disputa sin resolver (R18)."""
    if reserva.estado == Reserva.ESTADO_CON_DISPUTA:
        return True
    return Disputa.objects.filter(
        reserva_id=reserva.pk,
        estado__in=(Disputa.ESTADO_ABIERTA, Disputa.ESTADO_EN_REVISION),
    ).exists()


def _finalizar_entrega(reserva, actor, detalle, *, actor_pago=Pago.ACTOR_USUARIO):
    """Cierra una entrega, libera el pago y deja el evento en la bitácora."""
    if reserva.estado != Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR:
        raise ValidationError("Solo se puede confirmar una entrega marcada como entregada.")
    if _disputa_abierta(reserva):
        raise ValidationError(
            "No se puede confirmar la entrega: la reserva tiene una disputa abierta."
        )
    pago = _pago_activo(reserva)
    if pago is not None:
        if pago.estado == pagos_estados.RETENIDO:
            pagos_services.liberar_pago(
                pago, actor=_actor_pago(actor, actor_pago)
            )
        elif pago.estado != pagos_estados.LIBERADO:
            raise ValidationError("El pago de esta reserva no se puede liberar.")
    reserva.estado = Reserva.ESTADO_FINALIZADA
    reserva.confirmada_en = timezone.now()
    reserva.save(update_fields=["estado", "confirmada_en", "actualizada_en"])
    _evento(reserva, EventoReserva.TIPO_CONFIRMADA, actor, detalle)
    return reserva


# Confirmar entrega: cierra la reserva y libera el pago retenido.
@transaction.atomic
def confirmar_entrega(reserva, actor=None):
    return _finalizar_entrega(
        reserva,
        actor,
        "La organización confirmó la entrega. Se libera el pago.",
    )


def liberar_entregas_vencidas(ahora=None):
    """R18: libera entregas que la organización no confirmó en el plazo."""
    ahora = ahora or timezone.now()
    limite = ahora - timedelta(days=settings.PLAZO_REVISION_ORGANIZACION_DIAS)
    ids = list(
        Reserva.objects.filter(
            estado=Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR,
            entregado_en__isnull=False,
            entregado_en__lte=limite,
        ).values_list("pk", flat=True)
    )

    total = 0
    for pk in ids:
        with transaction.atomic():
            reserva = Reserva.objects.select_for_update().get(pk=pk)
            if reserva.estado != Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR:
                continue
            if _disputa_abierta(reserva):
                continue
            try:
                _finalizar_entrega(
                    reserva,
                    None,
                    "Venció el plazo de revisión de la organización. "
                    "Se libera el pago automáticamente.",
                    actor_pago=Pago.ACTOR_SISTEMA,
                )
            except (ValidationError, ErrorPasarela):
                logger.exception(
                    "No se pudo liberar automáticamente la reserva %s.", pk
                )
                continue
            total += 1
    return total


def cancelar(reserva, actor=None, motivo=""):
    """Cancela la reserva y reembolsa según la anticipación (24 h)."""
    original = reserva
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        if reserva.estado not in (
            Reserva.ESTADO_PENDIENTE_ACEPTACION,
            Reserva.ESTADO_EN_CURSO,
        ):
            raise ValidationError("Esta reserva ya no se puede cancelar.")
        porcentaje = porcentaje_reembolso(reserva)
        pago = _pago_activo(reserva)
        accion = _accion_sobre_pago(pago, porcentaje)

    if accion[0] == "cancelar":
        pagos_services.cancelar_pago(
            pago, actor=_actor_pago(actor, Pago.ACTOR_USUARIO)
        )
    elif accion[0] == "reembolsar":
        pagos_services.reembolsar_pago(
            pago,
            porcentaje=accion[1],
            actor=_actor_pago(actor, Pago.ACTOR_USUARIO),
        )

    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        if reserva.estado not in (
            Reserva.ESTADO_PENDIENTE_ACEPTACION,
            Reserva.ESTADO_EN_CURSO,
        ):
            raise ValidationError("Esta reserva ya no se puede cancelar.")
        reserva.estado = Reserva.ESTADO_CANCELADA
        reserva.motivo_cancelacion = (motivo or "").strip()
        reserva.cancelada_por = actor
        reserva.cancelada_en = timezone.now()
        reserva.save(
            update_fields=[
                "estado",
                "motivo_cancelacion",
                "cancelada_por",
                "cancelada_en",
                "actualizada_en",
            ]
        )
        detalle = f"Reserva cancelada. Reembolso del {porcentaje}%."
        if reserva.motivo_cancelacion:
            detalle = f"{detalle} Motivo: {reserva.motivo_cancelacion}"
        _evento(reserva, EventoReserva.TIPO_CANCELADA, actor, detalle)
    original.refresh_from_db()
    return original


def _accion_sobre_pago(pago, porcentaje_reembolso):
    """Decide si hay que revocar, reembolsar o no tocar el pago."""
    if pago is None:
        return (None, None)
    if pago.estado == pagos_estados.AUTORIZADO:
        return ("cancelar", None)
    if pago.estado in {pagos_estados.RETENIDO, pagos_estados.LIBERADO}:
        return ("reembolsar", porcentaje_reembolso)
    return (None, None)


def _validar_disputable(reserva):
    if reserva.estado not in (
        Reserva.ESTADO_EN_CURSO,
        Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR,
    ):
        raise ValidationError(
            "Solo se puede abrir una disputa de una reserva en curso o entregada."
        )


@transaction.atomic
def abrir_disputa(reserva, actor, motivo, descripcion=""):
    """Abre una disputa (tickets 5.1 y 5.2).

    Puede hacerlo la organización o el profesional de la reserva; la vista
    valida esa pertenencia antes de llamar acá. El pago queda retenido por el
    guard de R18 mientras la disputa no se resuelva.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Debes indicar el motivo de la disputa.")

    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
    _validar_disputable(reserva)
    if Disputa.objects.filter(reserva=reserva).exists():
        raise ValidationError("Esta reserva ya tiene una disputa registrada.")

    disputa = Disputa.objects.create(
        reserva=reserva,
        motivo=motivo[:200],
        descripcion=(descripcion or "").strip(),
        abierta_por=actor,
    )
    reserva.estado = Reserva.ESTADO_CON_DISPUTA
    reserva.save(update_fields=["estado", "actualizada_en"])
    _evento(
        reserva,
        EventoReserva.TIPO_PROBLEMA,
        actor,
        f"Se abrió una disputa: {disputa.motivo}",
    )
    return disputa


@transaction.atomic
def reportar_problema(reserva, actor=None, motivo="", descripcion=""):
    """Compatibilidad con el endpoint de reporte rápido de la organización."""
    if reserva.estado not in (
        Reserva.ESTADO_EN_CURSO,
        Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR,
    ):
        raise ValidationError("Solo se puede reportar un problema de una reserva en curso o entregada.")
    Disputa.objects.get_or_create(
        reserva=reserva,
        defaults={
            "motivo": (motivo or "").strip() or "Problema reportado por la organización",
            "descripcion": (descripcion or "").strip(),
            "abierta_por": actor,
        },
    )
    reserva.estado = Reserva.ESTADO_CON_DISPUTA
    reserva.save(update_fields=["estado", "actualizada_en"])
    _evento(
        reserva,
        EventoReserva.TIPO_PROBLEMA,
        actor,
        (descripcion or motivo or "La organización reportó un problema."),
    )
    return reserva


def agregar_evidencia(disputa, archivo, actor=None, nombre=""):
    """Adjunta un archivo a una disputa que todavía no se resolvió (5.2)."""
    if not disputa.esta_abierta:
        raise ValidationError("No se puede adjuntar evidencia a una disputa resuelta.")
    return EvidenciaDisputa.objects.create(
        disputa=disputa,
        archivo=archivo,
        nombre=(nombre or "").strip()[:200] or (getattr(archivo, "name", "") or "")[:200],
        subida_por=actor,
    )


def _resultado_sobre_pago(disputa, pago, resultado, porcentaje_reembolso, actor):
    """Aplica el resultado de la disputa sobre el pago (ticket 5.3)."""
    if resultado == Disputa.RESULTADO_PROFESIONAL:
        pagos_services.liberar_pago(
            pago,
            actor=_actor_pago(actor, Pago.ACTOR_ADMIN),
            ignorar_disputa=True,
        )
        return

    if resultado == Disputa.RESULTADO_ORGANIZACION:
        pagos_services.reembolsar_pago(
            pago, porcentaje=100, actor=_actor_pago(actor, Pago.ACTOR_ADMIN)
        )
        return

    # División: se devuelve el porcentaje acordado y el saldo se libera.
    pagos_services.reembolsar_pago(
        pago,
        porcentaje=porcentaje_reembolso,
        liberar_resto=True,
        actor=_actor_pago(actor, Pago.ACTOR_ADMIN),
    )


def _cerrar_disputa(disputa, actor, resultado, resolucion, porcentaje_reembolso, pago):
    ahora = timezone.now()
    disputa.estado = Disputa.ESTADO_RESUELTA
    disputa.resultado = resultado
    disputa.porcentaje_reembolso = porcentaje_reembolso
    disputa.resolucion = (resolucion or "").strip()
    disputa.resuelta_por = actor
    disputa.resuelta_en = ahora
    disputa.save(
        update_fields=[
            "estado",
            "resultado",
            "porcentaje_reembolso",
            "resolucion",
            "resuelta_por",
            "resuelta_en",
            "actualizada_en",
        ]
    )

    reserva = Reserva.objects.select_for_update().get(pk=disputa.reserva_id)
    reserva.estado = Reserva.ESTADO_FINALIZADA
    campos = ["estado", "actualizada_en"]
    if pago.estado == pagos_estados.LIBERADO:
        reserva.confirmada_en = ahora
        campos.append("confirmada_en")
    reserva.save(update_fields=campos)

    detalle = f"Disputa resuelta: {disputa.get_resultado_display()}."
    if disputa.resolucion:
        detalle = f"{detalle} {disputa.resolucion}"
    _evento(reserva, EventoReserva.TIPO_DISPUTA_RESUELTA, actor, detalle)
    return disputa


def resolver_disputa(
    disputa,
    actor,
    resultado,
    resolucion="",
    porcentaje_reembolso=None,
    gateway=None,
):
    """Resuelve una disputa y aplica el resultado sobre el pago (ticket 5.3).

    Los reembolsos hablan con la pasarela, así que la disputa pasa primero a
    'en_revision' y solo se marca resuelta cuando el pago confirma la acción.
    Si la pasarela falla, queda en revisión para que el admin reintente.
    """
    if resultado not in dict(Disputa.RESULTADO_CHOICES):
        raise ValidationError("El resultado de la disputa no es válido.")

    with transaction.atomic():
        disputa = Disputa.objects.select_for_update().get(pk=disputa.pk)
        if not disputa.esta_abierta:
            raise ValidationError("Esta disputa ya fue resuelta.")
        reserva = Reserva.objects.select_for_update().get(pk=disputa.reserva_id)
        pago = _pago_activo(reserva)
        if pago is None or pago.estado not in pagos_estados.ESTADOS_REEMBOLSABLES:
            raise ValidationError(
                "El pago de esta reserva no está retenido ni liberado; no se puede resolver."
            )

        if resultado == Disputa.RESULTADO_DIVISION:
            try:
                porcentaje = int(porcentaje_reembolso)
            except (TypeError, ValueError):
                raise ValidationError("Indica el porcentaje de reembolso de la división.")
            if not 1 <= porcentaje <= 99:
                raise ValidationError("El porcentaje de reembolso debe estar entre 1 y 99.")
        else:
            porcentaje = 0

        disputa.estado = Disputa.ESTADO_EN_REVISION
        disputa.save(update_fields=["estado", "actualizada_en"])

    _resultado_sobre_pago(disputa, pago, resultado, porcentaje, actor)

    with transaction.atomic():
        disputa = Disputa.objects.select_for_update().get(pk=disputa.pk)
        pago.refresh_from_db()
        return _cerrar_disputa(
            disputa, actor, resultado, resolucion, porcentaje, pago
        )


# Vencimiento (R12 / ticket 3.13)
def expirar_vencidas(ahora=None):
    """Pasa a 'vencida' las reservas cuyo plazo de respuesta expiró."""
    ahora = ahora or timezone.now()
    ids = list(
        Reserva.objects.filter(
            estado=Reserva.ESTADO_PENDIENTE_ACEPTACION, expira_en__lt=ahora
        ).values_list("pk", flat=True)
    )
    total = 0
    for pk in ids:
        with transaction.atomic():
            reserva = Reserva.objects.select_for_update().get(pk=pk)
            if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
                continue
            if not reserva.expira_en or reserva.expira_en >= ahora:
                continue
            pago = _pago_activo(reserva)
            accion = _accion_sobre_pago(pago, 100)

        try:
            if accion[0] == "cancelar":
                pagos_services.cancelar_pago(pago)
            elif accion[0] == "reembolsar":
                pagos_services.reembolsar_pago(pago, porcentaje=accion[1])
        except ErrorPasarela:
            logger.exception(
                "No se pudo resolver el pago %s al vencer la reserva %s.",
                pago.pk,
                pk,
            )
            continue

        with transaction.atomic():
            reserva = Reserva.objects.select_for_update().get(pk=pk)
            if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
                continue
            reserva.estado = Reserva.ESTADO_VENCIDA
            reserva.save(update_fields=["estado", "actualizada_en"])
            _evento(
                reserva,
                EventoReserva.TIPO_VENCIDA,
                None,
                "Venció el plazo de respuesta del profesional.",
            )
            total += 1
    return total


def buscar_por_token(token):
    """Reserva a la que apunta un token mágico válido, o None."""
    if not token:
        return None
    reserva = Reserva.objects.filter(token_hash=Reserva.hash_token(token)).first()
    if reserva and reserva.token_valido(token):
        return reserva
    return None

