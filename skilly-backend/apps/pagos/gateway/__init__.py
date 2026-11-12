"""Selección del adaptador de pago según `PAYMENT_GATEWAY`."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .fake import FakeGateway
from .transbank import CODIGOS_COMERCIO_INTEGRACION, TransbankGateway

GATEWAY_FAKE = "fake"
GATEWAY_TRANSBANK = "transbank"
GATEWAYS_VALIDOS = {GATEWAY_FAKE, GATEWAY_TRANSBANK}
ENTORNOS_TRANSBANK = {"integration", "production"}
LARGO_MAXIMO_RETURN_URL = 255


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
    if nombre != GATEWAY_TRANSBANK:
        return

    if (
        not getattr(settings, "TRANSBANK_COMMERCE_CODE", "")
        or not getattr(settings, "TRANSBANK_API_KEY_SECRET", "")
    ):
        raise ImproperlyConfigured(
            "PAYMENT_GATEWAY=transbank requiere TRANSBANK_COMMERCE_CODE y "
            "TRANSBANK_API_KEY_SECRET."
        )

    entorno = str(getattr(settings, "TRANSBANK_ENV", "integration")).strip().lower()
    if entorno not in ENTORNOS_TRANSBANK:
        raise ImproperlyConfigured(
            "TRANSBANK_ENV inválido. Usa 'integration' o 'production'."
        )

    return_url = str(getattr(settings, "TRANSBANK_RETURN_URL", "")).strip()
    if not return_url:
        raise ImproperlyConfigured("TRANSBANK_RETURN_URL es obligatorio.")
    if len(return_url) > LARGO_MAXIMO_RETURN_URL:
        raise ImproperlyConfigured(
            f"TRANSBANK_RETURN_URL supera los {LARGO_MAXIMO_RETURN_URL} caracteres."
        )

    timeout = getattr(settings, "TRANSBANK_TIMEOUT", 10)
    if not isinstance(timeout, int) or timeout <= 0:
        raise ImproperlyConfigured("TRANSBANK_TIMEOUT debe ser un entero positivo.")

    if entorno == "production":
        if not return_url.startswith("https://"):
            raise ImproperlyConfigured(
                "TRANSBANK_RETURN_URL debe usar HTTPS en producción."
            )
        if str(settings.TRANSBANK_COMMERCE_CODE) in CODIGOS_COMERCIO_INTEGRACION:
            raise ImproperlyConfigured(
                "No se puede usar un código de comercio de integración en producción."
            )
        if getattr(settings, "ALLOW_FAKE_GATEWAY", False):
            raise ImproperlyConfigured(
                "ALLOW_FAKE_GATEWAY debe ser False en producción."
            )


def get_gateway():
    validar_configuracion()
    nombre = getattr(settings, "PAYMENT_GATEWAY", GATEWAY_FAKE)
    if nombre == GATEWAY_FAKE:
        return FakeGateway()
    if nombre == GATEWAY_TRANSBANK:
        return TransbankGateway()
    raise ImproperlyConfigured(f"PAYMENT_GATEWAY inválido: {nombre!r}.")
