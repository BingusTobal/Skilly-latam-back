"""
Adaptador oficial de Webpay Plus usando `transbank-sdk`.

`Transaction` se configura con `TRANSBANK_ENV`: integración (`TEST`) o
producción (`LIVE`). Toda respuesta se sanea antes de guardarse y los errores
del SDK se traducen a `ErrorPasarela` para que `pagos.services` no dependa de
Transbank.
"""
import requests
from django.conf import settings
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes
from transbank.common.integration_type import IntegrationType
from transbank.common.options import WebpayOptions
from transbank.error.transbank_error import TransbankError
from transbank.webpay.webpay_plus.transaction import Transaction

from ..seguridad import sanear
from .base import (
    ErrorPasarela,
    PaymentGateway,
    ResultadoCreacion,
    ResultadoTransaccion,
)

CODIGOS_COMERCIO_INTEGRACION = {
    valor
    for nombre, valor in vars(IntegrationCommerceCodes).items()
    if not nombre.startswith("_")
    and isinstance(valor, str)
    and not nombre.endswith("CODES")
}

ESTADOS_TRANSBANK = {
    "FAILED": "REJECTED",
    "NULLIFIED": "REVERSED",
}


def _entero(datos, clave, defecto=None):
    valor = datos.get(clave, defecto) if isinstance(datos, dict) else defecto
    if valor in (None, ""):
        return defecto
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return defecto


def _texto(datos, clave, defecto=""):
    valor = datos.get(clave, defecto) if isinstance(datos, dict) else defecto
    return str(valor) if valor not in (None, "") else defecto


def _estado(datos):
    estado = _texto(datos, "status").upper()
    return ESTADOS_TRANSBANK.get(estado, estado)


def _respuesta(datos):
    return sanear(datos) if isinstance(datos, dict) else {}


def _tarjeta_ultimos4(datos):
    detalle = datos.get("card_detail") if isinstance(datos, dict) else None
    if not isinstance(detalle, dict):
        return ""
    numero = detalle.get("card_number") or ""
    return str(numero)[-4:] if numero else ""


def _resultado(data, *, ok, estado=None, monto=None):
    return ResultadoTransaccion(
        ok=ok,
        estado=estado if estado is not None else _estado(data),
        monto=_entero(data, "amount") if monto is None else monto,
        buy_order=_texto(data, "buy_order"),
        session_id=_texto(data, "session_id"),
        codigo_autorizacion=_texto(data, "authorization_code"),
        codigo_respuesta=_entero(data, "response_code"),
        tipo_pago=_texto(data, "payment_type_code"),
        cuotas=_entero(data, "installments_number", 0),
        tarjeta_ultimos4=_tarjeta_ultimos4(data),
        respuesta=_respuesta(data),
        error="",
    )


def _mensaje_error(exc):
    mensaje = getattr(exc, "message", "") or str(exc)
    return mensaje or "Error de comunicación con Transbank."


def _ya_capturada(exc):
    mensaje = _mensaje_error(exc).lower()
    return "already captured" in mensaje or "ya fue capturada" in mensaje or (
        "capturada" in mensaje and "ya" in mensaje
    )


class TransbankGateway(PaymentGateway):
    nombre = "transbank"

    def _transaction(self):
        entorno = (
            IntegrationType.LIVE
            if getattr(settings, "TRANSBANK_ENV", "integration") == "production"
            else IntegrationType.TEST
        )
        options = WebpayOptions(
            settings.TRANSBANK_COMMERCE_CODE,
            settings.TRANSBANK_API_KEY_SECRET,
            entorno,
            timeout=getattr(settings, "TRANSBANK_TIMEOUT", 10),
        )
        return Transaction(options)

    def _llamar(self, operacion):
        try:
            return operacion()
        except TransbankError as exc:
            raise ErrorPasarela(_mensaje_error(exc)) from exc
        except requests.RequestException as exc:
            raise ErrorPasarela(
                "No se pudo comunicar con Transbank. Intenta nuevamente."
            ) from exc

    def crear(self, buy_order, session_id, monto, return_url):
        data = self._llamar(
            lambda: self._transaction().create(
                buy_order, session_id, int(monto), return_url
            )
        )
        if not isinstance(data, dict) or not data.get("token") or not data.get("url"):
            return ResultadoCreacion(
                ok=False,
                error="Transbank no devolvió token y URL para la transacción.",
            )
        return ResultadoCreacion(
            ok=True,
            url=_texto(data, "url"),
            token=_texto(data, "token"),
            respuesta=sanear(data),
        )

    def confirmar(self, token):
        data = self._llamar(lambda: self._transaction().commit(token))
        estado = _estado(data)
        codigo = _entero(data, "response_code", 0)
        aprobado = codigo == 0 and estado in {"AUTHORIZED", "CAPTURED"}
        resultado = _resultado(data, ok=aprobado, estado=estado)
        if not aprobado:
            resultado.error = f"Transbank no autorizó el pago (código {codigo})."
        return resultado

    def estado(self, token):
        data = self._llamar(lambda: self._transaction().status(token))
        estado = _estado(data)
        return _resultado(data, ok=bool(estado), estado=estado)

    def capturar(self, token, buy_order, codigo_autorizacion, monto):
        try:
            data = self._llamar(
                lambda: self._transaction().capture(
                    token, buy_order, codigo_autorizacion, int(monto)
                )
            )
        except ErrorPasarela as exc:
            if _ya_capturada(exc):
                return ResultadoTransaccion(
                    ok=False,
                    estado="CAPTURED",
                    ya_capturada=True,
                    error=str(exc),
                )
            raise

        codigo = _entero(data, "response_code", 0)
        resultado = _resultado(
            data,
            ok=codigo == 0,
            estado="CAPTURED",
            monto=_entero(data, "captured_amount", int(monto)),
        )
        resultado.codigo_autorizacion = _texto(data, "authorization_code") or (
            codigo_autorizacion
        )
        if codigo != 0:
            resultado.error = f"Transbank rechazó la captura (código {codigo})."
        return resultado

    def reembolsar(self, token, monto):
        data = self._llamar(
            lambda: self._transaction().refund(token, int(monto))
        )
        codigo = _entero(data, "response_code", 0)
        resultado = _resultado(
            data,
            ok=codigo == 0,
            estado="REFUNDED",
            monto=_entero(data, "nullified_amount", int(monto)),
        )
        if codigo != 0:
            resultado.error = f"Transbank rechazó el reembolso (código {codigo})."
        return resultado
