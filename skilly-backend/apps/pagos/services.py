"""
Único lugar con la lógica de pagos.

Las llamadas externas a la pasarela se hacen siempre **fuera** de una
transacción de base de datos. Los estados transitorios (`capturando`,
`cancelando`, `reembolsando`) permiten separar la fase de bloqueo de la llamada
HTTP.
"""
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.reservas.models import Reserva

from . import estados
from .gateway import get_gateway
from .gateway.base import ErrorPasarela, permite_captura_diferida
from .models import Pago
from .seguridad import sanear


@dataclass
class InicioPago:
    pago: Pago
    url: str
    token: str


def pago_vigente(reserva):
    """Intento de pago que todavía bloquea la creación de uno nuevo."""
    return (
        Pago.objects.filter(
            reserva=reserva, estado__in=estados.ESTADOS_VIGENTES
        )
        .order_by("-creado_en")
        .first()
    )


def _buy_order(reserva):
    return f"SK{reserva.pk}{uuid.uuid4().hex}"[:26]


def _session_id(reserva):
    return f"rsv-{reserva.pk}-{uuid.uuid4().hex}"[:61]


def _plazo_pago(ahora=None):
    ahora = ahora or timezone.now()
    return ahora + timedelta(minutes=settings.MINUTOS_PAGO_PENDIENTE)


def _fusionar_respuesta(pago, respuesta):
    """Conserva datos previos y agrega la última respuesta ya saneada."""
    pago.respuesta_pasarela = {
        **(pago.respuesta_pasarela or {}),
        **sanear(respuesta),
    }


def calcular_reembolso(monto_total, porcentaje):
    """Monto de reembolso en CLP enteros, con redondeo comercial."""
    if porcentaje < 0 or porcentaje > 100:
        raise ValidationError("El porcentaje de reembolso debe estar entre 0 y 100.")
    monto = (Decimal(int(monto_total)) * Decimal(porcentaje) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(monto)


def iniciar_pago(reserva, *, gateway=None, actor=Pago.ACTOR_USUARIO, return_url=None):
    """Crea (o reutiliza) el intento de pago vigente y llama a la pasarela."""
    gateway = gateway or get_gateway()
    return_url = return_url or settings.TRANSBANK_RETURN_URL
    ahora = timezone.now()

    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
        activo = (
            Pago.objects.select_for_update()
            .filter(reserva=reserva, estado__in=estados.ESTADOS_VIGENTES)
            .order_by("-creado_en")
            .first()
        )
        if activo is not None:
            if activo.estado == estados.INICIADO and (
                activo.expira_en is None or activo.expira_en > ahora
            ):
                return InicioPago(activo, activo.url_pago, activo.token or "")
            if activo.estado == estados.INICIADO:
                activo.pasar_a(
                    estados.EXPIRADO,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo="Venció la ventana para completar el pago.",
                )
            else:
                raise ValidationError(
                    "La reserva ya tiene un pago en curso. Revisa su estado."
                )

        montos = Pago.calcular_montos(reserva)
        pago = Pago.objects.create(
            reserva=reserva,
            pasarela=gateway.nombre,
            buy_order=_buy_order(reserva),
            session_id=_session_id(reserva),
            expira_en=_plazo_pago(ahora),
            **montos,
        )
        pago.registrar_evento(
            "",
            estados.INICIADO,
            actor,
            motivo="Intento de pago iniciado.",
            datos={"pasarela": gateway.nombre},
        )

    try:
        resultado = gateway.crear(
            pago.buy_order, pago.session_id, pago.monto_total, return_url
        )
    except ErrorPasarela as exc:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.INICIADO:
                pago.pasar_a(
                    estados.RECHAZADO,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo="La pasarela no pudo crear la transacción.",
                )
        raise ValidationError(str(exc)) from exc

    if not resultado.ok:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.INICIADO:
                _fusionar_respuesta(pago, resultado.respuesta)
                pago.save(update_fields=["respuesta_pasarela", "actualizado_en"])
                pago.pasar_a(
                    estados.RECHAZADO,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo=resultado.error or "La pasarela rechazó la transacción.",
                )
        raise ValidationError(resultado.error or "La pasarela rechazó la transacción.")

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado != estados.INICIADO:
            return InicioPago(pago, pago.url_pago, pago.token or "")
        pago.token = resultado.token
        pago.url_pago = resultado.url
        _fusionar_respuesta(pago, resultado.respuesta)
        pago.save(
            update_fields=[
                "token",
                "url_pago",
                "respuesta_pasarela",
                "actualizado_en",
            ]
        )

    return InicioPago(pago, pago.url_pago, pago.token)


def _confirmar_con_reintento(gateway, token):
    """Si el commit falla por red, intenta reconciliar con `estado`."""
    try:
        return gateway.confirmar(token)
    except ErrorPasarela:
        return gateway.estado(token)


def confirmar_pago(token, *, gateway=None, actor=Pago.ACTOR_SISTEMA):
    """Confirma una transacción y actualiza el pago de forma idempotente."""
    gateway = gateway or get_gateway()
    pago = Pago.objects.filter(token=token).first()
    if pago is None:
        raise ValidationError("No existe un pago con ese token.")
    if pago.estado != estados.INICIADO:
        return pago

    try:
        resultado = _confirmar_con_reintento(gateway, token)
    except ErrorPasarela as exc:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.INICIADO:
                pago.pasar_a(
                    estados.REVISION_MANUAL,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo="No se pudo confirmar ni consultar el estado del pago.",
                    datos={"error": str(exc)},
                )
        return pago

    if not resultado.ok or resultado.estado not in {"AUTHORIZED", "CAPTURED"}:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado != estados.INICIADO:
                return pago
            pago.codigo_respuesta = resultado.codigo_respuesta
            _fusionar_respuesta(pago, resultado.respuesta)
            pago.save(
                update_fields=[
                    "codigo_respuesta",
                    "respuesta_pasarela",
                    "actualizado_en",
                ]
            )
            if resultado.estado == "EXPIRED":
                destino = estados.EXPIRADO
            elif not resultado.ok:
                destino = estados.RECHAZADO
            else:
                destino = estados.REVISION_MANUAL
            pago.pasar_a(
                destino,
                actor=actor,
                motivo=resultado.error or "La pasarela no confirmó el pago.",
            )
        return pago

    discrepancias = []
    if resultado.monto is not None and int(resultado.monto) != pago.monto_total:
        discrepancias.append("monto")
    if resultado.buy_order and resultado.buy_order != pago.buy_order:
        discrepancias.append("buy_order")
    if resultado.session_id and resultado.session_id != pago.session_id:
        discrepancias.append("session_id")

    if discrepancias:
        try:
            gateway.reembolsar(token, pago.monto_total)
        except ErrorPasarela:
            pass
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado != estados.INICIADO:
                return pago
            _fusionar_respuesta(pago, resultado.respuesta)
            pago.save(update_fields=["respuesta_pasarela", "actualizado_en"])
            pago.pasar_a(
                estados.REVISION_MANUAL,
                actor=Pago.ACTOR_SISTEMA,
                motivo=f"Respuesta inconsistente de la pasarela: {', '.join(discrepancias)}.",
            )
        return pago

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado != estados.INICIADO:
            return pago

        pago.codigo_autorizacion = resultado.codigo_autorizacion
        pago.tipo_pago = resultado.tipo_pago
        pago.cuotas = resultado.cuotas
        pago.tarjeta_ultimos4 = resultado.tarjeta_ultimos4
        pago.codigo_respuesta = resultado.codigo_respuesta
        pago.capturado_en_autorizacion = not permite_captura_diferida(
            resultado.tipo_pago
        )
        _fusionar_respuesta(pago, resultado.respuesta)
        pago.save(
            update_fields=[
                "codigo_autorizacion",
                "tipo_pago",
                "cuotas",
                "tarjeta_ultimos4",
                "codigo_respuesta",
                "capturado_en_autorizacion",
                "respuesta_pasarela",
                "actualizado_en",
            ]
        )
        destino = (
            estados.RETENIDO
            if pago.capturado_en_autorizacion
            else estados.AUTORIZADO
        )
        pago.pasar_a(
            destino,
            actor=actor,
            motivo=(
                "Pago confirmado: autorización diferida."
                if destino == estados.AUTORIZADO
                else "Pago confirmado y cobrado (débito/prepago)."
            ),
        )
    return pago


def capturar_pago(pago, *, gateway=None, actor=Pago.ACTOR_PROFESIONAL):
    """Captura una autorización en tres fases, sin HTTP dentro de la transacción."""
    gateway = gateway or get_gateway()

    if pago.estado == estados.RETENIDO or pago.capturado_en_autorizacion:
        return pago
    if pago.estado != estados.AUTORIZADO:
        raise ValidationError("Solo se puede capturar un pago autorizado.")

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado != estados.AUTORIZADO:
            return pago
        pago.pasar_a(
            estados.CAPTURANDO,
            actor=actor,
            motivo="Inicio de captura.",
        )

    try:
        resultado = gateway.capturar(
            pago.token, pago.buy_order, pago.codigo_autorizacion, pago.monto_total
        )
    except ErrorPasarela as exc:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.CAPTURANDO:
                pago.pasar_a(
                    estados.AUTORIZADO,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo="La captura falló y se puede reintentar.",
                    datos={"error": str(exc)},
                )
        raise

    if resultado.ya_capturada:
        try:
            conciliado = gateway.estado(pago.token)
        except ErrorPasarela:
            conciliado = None
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.CAPTURANDO:
                if conciliado and conciliado.estado in {"CAPTURED", "AUTHORIZED"}:
                    pago.pasar_a(
                        estados.RETENIDO,
                        actor=Pago.ACTOR_SISTEMA,
                        motivo="La captura ya estaba realizada.",
                    )
                else:
                    pago.pasar_a(
                        estados.REVISION_MANUAL,
                        actor=Pago.ACTOR_SISTEMA,
                        motivo="La pasarela informa una captura previa no conciliable.",
                    )
        return pago

    if not resultado.ok:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.CAPTURANDO:
                pago.pasar_a(
                    estados.AUTORIZADO,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo=resultado.error or "La captura fue rechazada.",
                )
        raise ErrorPasarela(resultado.error or "La captura fue rechazada.")

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado == estados.CAPTURANDO:
            _fusionar_respuesta(pago, resultado.respuesta)
            pago.save(update_fields=["respuesta_pasarela", "actualizado_en"])
            pago.pasar_a(
                estados.RETENIDO,
                actor=actor,
                motivo="Captura confirmada por la pasarela.",
            )
    return pago


def liberar_pago(pago, *, actor=Pago.ACTOR_ADMIN):
    """Marca que el neto corresponde al profesional. No llama a la pasarela."""
    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado == estados.LIBERADO:
            return pago
        if pago.estado != estados.RETENIDO:
            raise ValidationError("Solo se puede liberar un pago retenido.")
        pago.pasar_a(
            estados.LIBERADO,
            actor=actor,
            motivo="Entrega confirmada: el neto corresponde al profesional.",
        )
    return pago


def reembolsar_pago(
    pago,
    *,
    monto=None,
    porcentaje=None,
    gateway=None,
    actor=Pago.ACTOR_ADMIN,
):
    """Reembolsa total o parcialmente un pago retenido/liberado."""
    gateway = gateway or get_gateway()

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado == estados.REEMBOLSADO:
            return pago
        if pago.estado not in estados.ESTADOS_REEMBOLSABLES:
            raise ValidationError("Solo se puede reembolsar un pago retenido o liberado.")

        disponible = pago.monto_total - pago.monto_reembolsado
        if monto is None:
            monto = calcular_reembolso(
                pago.monto_total, 100 if porcentaje is None else porcentaje
            )
        if monto <= 0 or monto > disponible:
            raise ValidationError(
                "El monto de reembolso debe ser mayor que cero y no superar el saldo."
            )
        pago.pasar_a(
            estados.REEMBOLSANDO,
            actor=actor,
            motivo=f"Reembolso de ${monto} CLP en curso.",
            datos={"monto": monto},
        )

    try:
        resultado = gateway.reembolsar(pago.token, monto)
    except ErrorPasarela as exc:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.REEMBOLSANDO:
                pago.pasar_a(
                    estados.REVISION_MANUAL,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo="La pasarela falló al reembolsar.",
                    datos={"error": str(exc), "monto": monto},
                )
        raise

    if not resultado.ok:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.REEMBOLSANDO:
                pago.pasar_a(
                    estados.REVISION_MANUAL,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo=resultado.error or "La pasarela rechazó el reembolso.",
                    datos={"monto": monto},
                )
        raise ErrorPasarela(resultado.error or "La pasarela rechazó el reembolso.")

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado != estados.REEMBOLSANDO:
            return pago
        pago.monto_reembolsado += monto
        _fusionar_respuesta(pago, resultado.respuesta)
        pago.save(
            update_fields=[
                "monto_reembolsado",
                "respuesta_pasarela",
                "actualizado_en",
            ]
        )
        pago.pasar_a(
            estados.REEMBOLSADO,
            actor=actor,
            motivo=f"Reembolso de ${monto} CLP confirmado.",
            datos={"monto": monto},
        )
    return pago


def cancelar_pago(pago, *, gateway=None, actor=Pago.ACTOR_ADMIN):
    """Revoca una autorización sin captura usando `refund` (ver hallazgo 4)."""
    gateway = gateway or get_gateway()

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado == estados.CANCELADO:
            return pago
        if pago.estado != estados.AUTORIZADO:
            raise ValidationError("Solo se puede cancelar un pago autorizado.")
        pago.pasar_a(
            estados.CANCELANDO,
            actor=actor,
            motivo="Revocando autorización sin captura.",
        )

    try:
        resultado = gateway.reembolsar(pago.token, pago.monto_total)
    except ErrorPasarela as exc:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.CANCELANDO:
                pago.pasar_a(
                    estados.REVISION_MANUAL,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo="La pasarela falló al revocar la autorización.",
                    datos={"error": str(exc)},
                )
        raise

    if not resultado.ok:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado == estados.CANCELANDO:
                pago.pasar_a(
                    estados.REVISION_MANUAL,
                    actor=Pago.ACTOR_SISTEMA,
                    motivo=resultado.error or "La pasarela rechazó la revocación.",
                )
        raise ErrorPasarela(resultado.error or "La pasarela rechazó la revocación.")

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado != estados.CANCELANDO:
            return pago
        _fusionar_respuesta(pago, resultado.respuesta)
        pago.save(update_fields=["respuesta_pasarela", "actualizado_en"])
        pago.pasar_a(
            estados.CANCELADO,
            actor=actor,
            motivo="Autorización revocada sin cargo.",
        )
    return pago


def expirar_pago(pago, *, actor=Pago.ACTOR_SISTEMA):
    """Expira un intento que nunca se completó."""
    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if pago.estado == estados.EXPIRADO:
            return pago
        if pago.estado not in {estados.INICIADO, estados.AUTORIZADO}:
            raise ValidationError("Este pago no se puede expirar.")
        pago.pasar_a(
            estados.EXPIRADO,
            actor=actor,
            motivo="Venció el plazo del intento de pago.",
        )
    return pago


def expirar_pagos_vencidos(ahora=None):
    """Marca expirados los intentos `iniciado` cuya ventana ya venció."""
    ahora = ahora or timezone.now()
    pagos = Pago.objects.filter(
        estado=estados.INICIADO, expira_en__lt=ahora
    ).order_by("expira_en")
    total = 0
    for pago in pagos:
        with transaction.atomic():
            pago = Pago.objects.select_for_update().get(pk=pago.pk)
            if pago.estado != estados.INICIADO or pago.expira_en >= ahora:
                continue
            pago.pasar_a(
                estados.EXPIRADO,
                actor=Pago.ACTOR_SISTEMA,
                motivo="Venció la ventana para completar el pago.",
            )
            total += 1
    return total
