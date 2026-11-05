"""
Puerto de la pasarela de pago.

`reservas` y `pagos.services` hablan solo con esta interfaz. El adaptador
concreto (`FakeGateway`, `TransbankGateway`) se elige con `PAYMENT_GATEWAY`.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

TIPO_PAGO_DEBITO = {"VD"}
TIPO_PAGO_PREPAGO = {"VP"}
TIPOS_SIN_CAPTURA_DIFERIDA = TIPO_PAGO_DEBITO | TIPO_PAGO_PREPAGO


class ErrorPasarela(Exception):
    """Error de transporte o de configuración al hablar con la pasarela."""


def permite_captura_diferida(tipo_pago):
    """Solo el crédito admite autorizar ahora y capturar después."""
    return (tipo_pago or "").upper() not in TIPOS_SIN_CAPTURA_DIFERIDA


@dataclass
class ResultadoCreacion:
    ok: bool
    url: str = ""
    token: str = ""
    respuesta: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class ResultadoTransaccion:
    ok: bool
    estado: str = ""
    monto: int | None = None
    buy_order: str = ""
    session_id: str = ""
    codigo_autorizacion: str = ""
    codigo_respuesta: int | None = None
    tipo_pago: str = ""
    cuotas: int = 0
    tarjeta_ultimos4: str = ""
    ya_capturada: bool = False
    respuesta: dict = field(default_factory=dict)
    error: str = ""


class PaymentGateway(ABC):
    """Contrato mínimo que deben cumplir todos los adaptadores."""

    nombre = "base"

    @abstractmethod
    def crear(self, buy_order, session_id, monto, return_url):
        """Crea una transacción y devuelve la URL de Webpay y su token."""

    @abstractmethod
    def confirmar(self, token):
        """Confirma (commit) una transacción por su token."""

    @abstractmethod
    def estado(self, token):
        """Consulta el estado de una transacción por su token."""

    @abstractmethod
    def capturar(self, token, buy_order, codigo_autorizacion, monto):
        """Captura total o parcialmente una autorización."""

    @abstractmethod
    def reembolsar(self, token, monto):
        """Anula o reembolsa una transacción."""
