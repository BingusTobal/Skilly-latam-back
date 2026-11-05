import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.pagos.gateway import get_gateway, validar_configuracion
from apps.pagos.gateway.fake import FakeGateway


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
        settings.PAYMENT_GATEWAY = "transbank"
        settings.TRANSBANK_COMMERCE_CODE = ""
        settings.TRANSBANK_API_KEY_SECRET = ""
        with pytest.raises(ImproperlyConfigured):
            validar_configuracion()

    def test_transbank_pendiente_de_fase_2(self, settings):
        settings.PAYMENT_GATEWAY = "transbank"
        settings.TRANSBANK_COMMERCE_CODE = "597055555540"
        settings.TRANSBANK_API_KEY_SECRET = "secreto"
        validar_configuracion()
        with pytest.raises(ImproperlyConfigured):
            get_gateway()
