import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.pagos.gateway import get_gateway, validar_configuracion
from apps.pagos.gateway.fake import FakeGateway
from apps.pagos.gateway.transbank import TransbankGateway


def _configurar_transbank(settings, **overrides):
    settings.PAYMENT_GATEWAY = "transbank"
    settings.TRANSBANK_COMMERCE_CODE = "597055555540"
    settings.TRANSBANK_API_KEY_SECRET = "secreto-de-prueba"
    settings.TRANSBANK_ENV = "integration"
    settings.TRANSBANK_RETURN_URL = (
        "http://localhost:8000/api/pagos/transbank/retorno/"
    )
    settings.TRANSBANK_TIMEOUT = 10
    settings.ALLOW_FAKE_GATEWAY = False
    for clave, valor in overrides.items():
        setattr(settings, clave, valor)


@pytest.mark.pagos
class TestConfiguracionGateway:
    def test_fake_habilitado_en_tests(self, settings):
        settings.PAYMENT_GATEWAY = "fake"
        settings.DEBUG = False
        settings.ALLOW_FAKE_GATEWAY = True
        validar_configuracion()
        assert isinstance(get_gateway(), FakeGateway)

    def test_fake_prohibido_fuera_de_debug(self, settings):
        settings.PAYMENT_GATEWAY = "fake"
        settings.DEBUG = False
        settings.ALLOW_FAKE_GATEWAY = False
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_gateway_desconocido(self, settings):
        settings.PAYMENT_GATEWAY = "otro"
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_transbank_sin_credenciales(self, settings):
        _configurar_transbank(settings)
        settings.TRANSBANK_COMMERCE_CODE = ""
        settings.TRANSBANK_API_KEY_SECRET = ""
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_transbank_integracion_configurado(self, settings):
        _configurar_transbank(settings)
        validar_configuracion()
        assert isinstance(get_gateway(), TransbankGateway)

    def test_transbank_entorno_invalido(self, settings):
        _configurar_transbank(settings, TRANSBANK_ENV="sandbox")
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_transbank_return_url_vacia(self, settings):
        _configurar_transbank(settings, TRANSBANK_RETURN_URL="")
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_transbank_return_url_demasiado_larga(self, settings):
        _configurar_transbank(settings, TRANSBANK_RETURN_URL="https://a.cl/" + "x" * 250)
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_transbank_timeout_invalido(self, settings):
        _configurar_transbank(settings, TRANSBANK_TIMEOUT=0)
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_produccion_exige_https(self, settings):
        _configurar_transbank(
            settings,
            TRANSBANK_ENV="production",
            TRANSBANK_COMMERCE_CODE="597012345678",
            TRANSBANK_RETURN_URL="http://api.skilly.cl/api/pagos/transbank/retorno/",
        )
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_produccion_rechaza_codigo_de_integracion(self, settings):
        _configurar_transbank(
            settings,
            TRANSBANK_ENV="production",
            TRANSBANK_COMMERCE_CODE="597055555540",
            TRANSBANK_RETURN_URL="https://api.skilly.cl/api/pagos/transbank/retorno/",
        )
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_produccion_rechaza_fake_habilitado(self, settings):
        _configurar_transbank(
            settings,
            TRANSBANK_ENV="production",
            TRANSBANK_COMMERCE_CODE="597012345678",
            TRANSBANK_RETURN_URL="https://api.skilly.cl/api/pagos/transbank/retorno/",
            ALLOW_FAKE_GATEWAY=True,
        )
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_produccion_configurada(self, settings):
        _configurar_transbank(
            settings,
            TRANSBANK_ENV="production",
            TRANSBANK_COMMERCE_CODE="597012345678",
            TRANSBANK_RETURN_URL="https://api.skilly.cl/api/pagos/transbank/retorno/",
        )
        validar_configuracion()
        assert isinstance(get_gateway(), TransbankGateway)
