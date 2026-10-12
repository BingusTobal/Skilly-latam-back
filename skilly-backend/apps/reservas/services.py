"""
Lógica de reservas: cálculo de disponibilidad y máquina de estados.

Ticket 3.1 (slots) y 3.2 (máquina de estados). Toda transición de estado pasa
por acá y deja un `EventoReserva`, para que la bitácora sea consistente sin
importar quién dispare la acción (API, admin o un comando).

Regla de bloqueo (R11): una reserva vigente bloquea los slots dentro de las
`HORAS_BLOQUEO_RESERVA` horas siguientes a su inicio. Reservar a las 16:00 con
un colchón de 3 h deja libres recién desde las 19:00.
"""
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
from apps.usuarios.correo import enviar_cuenta_creada, enviar_reserva_registrada
from apps.usuarios.models import Horario, Organizacion, validar_rut

from .models import Disputa, EventoReserva, Reserva

Usuario = get_user_model()
ZONA = timezone.get_current_timezone()


# ---------------------------------------------------------------------------
# Utilidades de tiempo
# ---------------------------------------------------------------------------
def aware(fecha, hora):
    """Combina fecha y hora locales (America/Santiago) en un datetime aware."""
    return timezone.make_aware(datetime.combine(fecha, hora), ZONA)


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


# ---------------------------------------------------------------------------
# Creación de la reserva (ticket 3.5)
# ---------------------------------------------------------------------------
def _crear_usuario_invitado(datos):
    """Crea la cuenta automática de una reserva sin registro.

    Nace con contraseña inutilizable: el invitado la define al activar la
    cuenta desde el correo. Ver decisión del Sprint 3 sobre reserva de invitado.
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


def _crear_organizacion_invitada(datos, usuario):
    rut = (datos.get("rut") or "").strip()
    if rut:
        try:
            validar_rut(rut)
            rut_limpio = rut.replace(".", "").replace("-", "").upper()
        except ValueError:
            rut_limpio = None
    else:
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
    """
    if organizacion is not None:
        return organizacion, None
    if creada_por is not None:
        return getattr(creada_por, "organizacion", None), None

    email = Usuario.objects.normalize_email(datos["email"]).lower()
    usuario = Usuario.objects.filter(email__iexact=email).first()

    if usuario is not None:
        existente = getattr(usuario, "organizacion", None)
        if existente is not None:
            return existente, {"cuenta": "existente", "usuario": usuario}
        if usuario.tipo == Usuario.TIPO_ORGANIZACION:
            # El usuario tiene cuenta tipo organizacion pero sin perfil: intentar
            # reutilizar por RUT si existe para no violar UNIQUE; de lo contrario
            # crear org e intentar guardar.
            rut = (datos.get("rut") or "").strip()
            rut_limpio = rut
            if rut:
                try:
                    validar_rut(rut)
                    rut_limpio = rut.replace(".", "").replace("-", "").upper()
                except ValueError:
                    rut_limpio = None
            if rut_limpio:
                existente_rut = Organizacion.objects.filter(rut=rut_limpio).first()
                if existente_rut is not None:
                    if existente_rut.usuario_id is not None:
                        return existente_rut, {
                            "cuenta": "existente",
                            "usuario": existente_rut.usuario,
                        }
                    existente_rut.usuario = usuario
                    existente_rut.modo = Organizacion.MODO_INVITADA
                    existente_rut.save(update_fields=["usuario", "modo"])
                    return existente_rut, {"cuenta": "existente", "usuario": usuario}
            organizacion = _crear_organizacion_invitada(datos, usuario)
            return organizacion, {"cuenta": "existente", "usuario": usuario}
        # Profesional o admin: no se le cuelga una organización.
        organizacion = _crear_organizacion_invitada(datos, None)
        return organizacion, {"cuenta": None, "usuario": None}

    rut = (datos.get("rut") or "").strip()
    if rut:
        try:
            validar_rut(rut)
            rut_limpio = rut.replace(".", "").replace("-", "").upper()
        except ValueError:
            rut_limpio = None
        if rut_limpio:
            existente = Organizacion.objects.filter(rut=rut_limpio).first()
            if existente is not None:
                if existente.usuario_id is not None:
                    return existente, {"cuenta": "existente", "usuario": existente.usuario}
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

    if isinstance(hora_inicio, str):
        hora_inicio = _time.fromisoformat(hora_inicio)

    if fecha < timezone.localdate():
        raise ValidationError("No se puede reservar en una fecha pasada.")

    inicio_dt = aware(fecha, hora_inicio)
    if inicio_dt <= timezone.now():
        raise ValidationError("Ese horario ya pasó. Elige otro.")

    slots = calcular_slots(servicio, fecha)
    disponible = any(
        s["disponible"] and s["hora_inicio"].time() == hora_inicio for s in slots
    )
    if not disponible:
        raise ValidationError("Ese bloque ya no está disponible. Elige otro horario.")

    buffer = timedelta(hours=settings.HORAS_BLOQUEO_RESERVA)
    hora_fin = (inicio_dt + buffer).time()

    organizacion, aviso = _resolver_organizacion(organizacion, creada_por, datos)

    plazo = settings.PLAZO_RESPUESTA_PROFESIONAL_HORAS
    reserva = Reserva.objects.create(
        servicio=servicio,
        profesional=servicio.profesional,
        organizacion=organizacion,
        creada_por=creada_por,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        precio_acordado=servicio.precio,
        formato=servicio.formato,
        ubicacion=servicio.ubicacion,
        contacto_nombre=datos.get("nombre", ""),
        contacto_email=datos["email"],
        contacto_telefono=datos.get("telefono", ""),
        mensaje=datos.get("mensaje", ""),
        expira_en=timezone.now() + timedelta(hours=plazo),
    )
    EventoReserva.objects.create(
        reserva=reserva,
        tipo=EventoReserva.TIPO_CREADA,
        actor=creada_por,
        detalle="Solicitud de reserva creada.",
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


# ---------------------------------------------------------------------------
# Máquina de estados (ticket 3.2)
# ---------------------------------------------------------------------------
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


@transaction.atomic
def aceptar(reserva, actor=None):
    if reserva.estado != Reserva.ESTADO_PENDIENTE_ACEPTACION:
        raise ValidationError("Esta reserva ya no está pendiente de aceptación.")
    if reserva.expirada:
        raise ValidationError("El plazo para responder esta solicitud venció.")
    reserva.estado = Reserva.ESTADO_EN_CURSO
    reserva.aceptada_en = timezone.now()
    reserva.save(update_fields=["estado", "aceptada_en", "actualizada_en"])
    _evento(reserva, EventoReserva.TIPO_ACEPTADA, actor, "El profesional aceptó la solicitud.")
    return reserva


@transaction.atomic
def rechazar(reserva, actor=None, motivo=""):
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
    return reserva


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


@transaction.atomic
def confirmar_entrega(reserva, actor=None):
    if reserva.estado != Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR:
        raise ValidationError("Solo se puede confirmar una entrega marcada como entregada.")
    reserva.estado = Reserva.ESTADO_FINALIZADA
    reserva.confirmada_en = timezone.now()
    reserva.save(update_fields=["estado", "confirmada_en", "actualizada_en"])
    _evento(
        reserva,
        EventoReserva.TIPO_CONFIRMADA,
        actor,
        "La organización confirmó la entrega. Se libera el pago (simulado).",
    )
    return reserva


@transaction.atomic
def cancelar(reserva, actor=None, motivo=""):
    if reserva.estado not in (
        Reserva.ESTADO_PENDIENTE_ACEPTACION,
        Reserva.ESTADO_EN_CURSO,
    ):
        raise ValidationError("Esta reserva ya no se puede cancelar.")
    porcentaje = porcentaje_reembolso(reserva)
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
    detalle = f"Reserva cancelada. Reembolso del {porcentaje}% (simulado)."
    if reserva.motivo_cancelacion:
        detalle = f"{detalle} Motivo: {reserva.motivo_cancelacion}"
    _evento(reserva, EventoReserva.TIPO_CANCELADA, actor, detalle)
    return reserva


@transaction.atomic
def reportar_problema(reserva, actor=None, motivo="", descripcion=""):
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


# ---------------------------------------------------------------------------
# Vencimiento (R12 / ticket 3.13)
# ---------------------------------------------------------------------------
def expirar_vencidas(ahora=None):
    """Pasa a 'vencida' las reservas pendientes cuyo plazo ya expiró."""
    ahora = ahora or timezone.now()
    pendientes = Reserva.objects.filter(
        estado=Reserva.ESTADO_PENDIENTE_ACEPTACION, expira_en__lt=ahora
    )
    total = 0
    for reserva in pendientes:
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

