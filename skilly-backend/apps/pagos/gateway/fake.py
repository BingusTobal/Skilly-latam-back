"""
Pasarela simulada y configurable.

Reemplaza la pasarela de juguete de `apps/reservas/pagos.py`. Guarda las
transacciones en memoria y comparte la configuración entre instancias para que
`crear()` y `confirmar()` puedan ocurrir en objetos distintos.
"""
import time
import uuid

from .base import (
    ErrorPasarela,
    PaymentGateway,
    ResultadoCreacion,
    ResultadoTransaccion,
)

_CONFIG_INICIAL = {
    "modo": "aprobar",
    "monto_alterado": None,
    "tipo_pago": "VC",
    "cuotas": 0,
    "demora": 0,
    "crear_falla": False,
    "confirmar_falla": False,
    "estado_falla": False,
    "capturar_falla": False,
    "ya_capturada": False,
    "reembolsar_falla": False,
}


class FakeGateway(PaymentGateway):
    nombre = "fake"
    _transacciones = {}
    _config = dict(_CONFIG_INICIAL)

    def __init__(self, **config):
        if config:
            self.configurar(**config)

    @classmethod
    def configurar(cls, **config):
        claves = set(_CONFIG_INICIAL)
        desconocidas = set(config) - claves
        if desconocidas:
            raise ValueError(f"Configuración fake desconocida: {sorted(desconocidas)}")
        cls._config.update(config)

    @classmethod
    def reiniciar(cls):
        cls._transacciones.clear()
        cls._config = dict(_CONFIG_INICIAL)

    @classmethod
    def transaccion(cls, token):
        return cls._transacciones.get(token)

    def _esperar(self):
        demora = self._config.get("demora") or 0
        if demora:
            time.sleep(demora)

    def _falla(self, operacion):
        return self._config.get("modo") == "fallar" or self._config.get(
            f"{operacion}_falla", False
        )

    def crear(self, buy_order, session_id, monto, return_url):
        self._esperar()
        if self._falla("crear"):
            raise ErrorPasarela("La pasarela simulada falló al crear la transacción.")
        token = f"FAKE-{uuid.uuid4().hex}"
        self._transacciones[token] = {
            "buy_order": buy_order,
            "session_id": session_id,
            "monto": monto,
            "return_url": return_url,
            "estado": "INITIALIZED",
            "capturada": False,
        }
        return ResultadoCreacion(
            ok=True,
            url=f"https://fake.webpay.cl/webpay?token={token}",
            token=token,
            respuesta={
                "token": token,
                "url": f"https://fake.webpay.cl/webpay?token={token}",
                "card_number": "4051885600446623",
            },
        )

    def _resultado(self, token, estado, **extra):
        datos = self._transacciones[token]
        return ResultadoTransaccion(
            ok=extra.pop("ok", True),
            estado=estado,
            monto=extra.pop("monto", datos["monto"]),
            buy_order=datos["buy_order"],
            session_id=datos["session_id"],
            codigo_autorizacion=extra.pop("codigo_autorizacion", "123456"),
            codigo_respuesta=extra.pop("codigo_respuesta", 0),
            tipo_pago=extra.pop("tipo_pago", self._config["tipo_pago"]),
            cuotas=extra.pop("cuotas", self._config["cuotas"]),
            tarjeta_ultimos4=extra.pop("tarjeta_ultimos4", "6623"),
            ya_capturada=extra.pop("ya_capturada", False),
            respuesta=self._transacciones[token],
            error=extra.pop("error", ""),
        )

    def confirmar(self, token):
        self._esperar()
        if self._falla("confirmar"):
            raise ErrorPasarela("La pasarela simulada falló al confirmar.")
        if token not in self._transacciones:
            return ResultadoTransaccion(ok=False, estado="ERROR", error="Token desconocido.")

        modo = self._config["modo"]
        if modo in {"rechazar", "abandonar"}:
            self._transacciones[token]["estado"] = "REJECTED"
            return self._resultado(
                token,
                "REJECTED",
                ok=False,
                codigo_respuesta=1,
                codigo_autorizacion="",
                error="Pago rechazado por la pasarela simulada.",
            )
        if modo == "expirado":
            self._transacciones[token]["estado"] = "EXPIRED"
            return self._resultado(
                token,
                "EXPIRED",
                ok=False,
                codigo_respuesta=1,
                codigo_autorizacion="",
                error="Token expirado en la pasarela simulada.",
            )

        self._transacciones[token]["estado"] = "AUTHORIZED"
        monto = self._config["monto_alterado"]
        return self._resultado(
            token,
            "AUTHORIZED",
            monto=monto if monto is not None else self._transacciones[token]["monto"],
        )

    def estado(self, token):
        self._esperar()
        if self._falla("estado"):
            raise ErrorPasarela("La pasarela simulada falló al consultar el estado.")
        if token not in self._transacciones:
            return ResultadoTransaccion(ok=False, estado="ERROR", error="Token desconocido.")
        return self._resultado(token, self._transacciones[token]["estado"])

    def capturar(self, token, buy_order, codigo_autorizacion, monto):
        self._esperar()
        if self._falla("capturar"):
            raise ErrorPasarela("La pasarela simulada falló al capturar.")
        if token not in self._transacciones:
            return ResultadoTransaccion(ok=False, estado="ERROR", error="Token desconocido.")
        if self._config["ya_capturada"] or self._transacciones[token]["capturada"]:
            return self._resultado(
                token,
                self._transacciones[token]["estado"],
                ok=False,
                ya_capturada=True,
                error="La transacción ya fue capturada.",
            )
        self._transacciones[token]["capturada"] = True
        self._transacciones[token]["estado"] = "CAPTURED"
        return self._resultado(token, "CAPTURED", monto=monto)

    def reembolsar(self, token, monto):
        self._esperar()
        if self._falla("reembolsar"):
            raise ErrorPasarela("La pasarela simulada falló al reembolsar.")
        if token not in self._transacciones:
            return ResultadoTransaccion(ok=False, estado="ERROR", error="Token desconocido.")
        self._transacciones[token]["estado"] = "REFUNDED"
        return self._resultado(token, "REFUNDED", monto=monto)
