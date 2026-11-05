"""Selección del adaptador de pago según `PAYMENT_GATEWAY`."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .fake import FakeGateway

GATEWAY_FAKE = "fake"
GATEWAY_TRANSBANK = "transbank"
GATEWAYS_VALIDOS = {GATEWAY_FAKE, GATEWAY_TRANSBANK}


def validar_configuracion():
    """Falla rápido ante una configuración de pagos insegura o incompleta."""
    nombre = getattr(settings, "PAYMENT_GATEWAY", GATEWAY_FAKE)
    if nombre not in GATEWAYS_VALIDOS:
        raise ImproperlyConfigured(
            f"PAYMENT_GATEWAY inválido: {nombre!r}. Usa 'fake' o 'transbank'."
        )
    if nombre == GATEWAY_FAKE and not settings.DEBUG and not getattr(
        settings, "ALLOW_FAKE_GATEWAY", False
    ):
        raise ImproperlyConfigured(
            "PAYMENT_GATEWAY=fake requiere ALLOW_FAKE_GATEWAY=True fuera de DEBUG."
        )
    if nombre == GATEWAY_TRANSBANK and (
        not getattr(settings, "TRANSBANK_COMMERCE_CODE", "")
        or not getattr(settings, "TRANSBANK_API_KEY_SECRET", "")
    ):
        raise ImproperlyConfigured(
            "PAYMENT_GATEWAY=transbank requiere TRANSBANK_COMMERCE_CODE y "
            "TRANSBANK_API_KEY_SECRET."
        )


def get_gateway():
    validar_configuracion()
    nombre = getattr(settings, "PAYMENT_GATEWAY", GATEWAY_FAKE)
    if nombre == GATEWAY_FAKE:
        return FakeGateway()
    if nombre == GATEWAY_TRANSBANK:
        raise ImproperlyConfigured(
            "TransbankGateway se habilita en la Fase 2 de docs/PAGOS_TRANSBANK.md."
        )
    raise ImproperlyConfigured(f"PAYMENT_GATEWAY inválido: {nombre!r}.")
