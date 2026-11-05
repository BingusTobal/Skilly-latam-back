import pytest

from apps.pagos.gateway.base import ErrorPasarela
from apps.pagos.gateway.fake import FakeGateway


@pytest.mark.pagos
class TestFakeGateway:
    def _crear(self, monto=10000):
        return FakeGateway().crear("SK-1", "sesion-1", monto, "http://localhost/retorno")

    def test_crear_devuelve_token_y_url(self):
        resultado = self._crear()
        assert resultado.ok
        assert resultado.token.startswith("FAKE-")
        assert "token=" in resultado.url
        assert FakeGateway.transaccion(resultado.token)["monto"] == 10000

    def test_confirmar_aprobado(self):
        creada = self._crear()
        resultado = FakeGateway().confirmar(creada.token)
        assert resultado.ok
        assert resultado.estado == "AUTHORIZED"
        assert resultado.monto == 10000
        assert resultado.codigo_respuesta == 0
        assert resultado.tipo_pago == "VC"

    def test_confirmar_rechazado(self):
        FakeGateway.configurar(modo="rechazar")
        creada = self._crear()
        resultado = FakeGateway().confirmar(creada.token)
        assert not resultado.ok
        assert resultado.estado == "REJECTED"
        assert resultado.codigo_respuesta == 1

    def test_confirmar_monto_alterado(self):
        FakeGateway.configurar(monto_alterado=999)
        creada = self._crear()
        resultado = FakeGateway().confirmar(creada.token)
        assert resultado.ok
        assert resultado.monto == 999

    def test_confirmar_token_desconocido(self):
        resultado = FakeGateway().confirmar("no-existe")
        assert not resultado.ok
        assert resultado.error

    def test_fallar_confirmar_lanza_error(self):
        creada = self._crear()
        FakeGateway.configurar(modo="fallar")
        with pytest.raises(ErrorPasarela):
            FakeGateway().confirmar(creada.token)

    def test_capturar_y_detectar_ya_capturada(self):
        creada = self._crear()
        gateway = FakeGateway()
        gateway.confirmar(creada.token)
        resultado = gateway.capturar(creada.token, "SK-1", "123456", 10000)
        assert resultado.ok
        assert resultado.estado == "CAPTURED"

        repetida = gateway.capturar(creada.token, "SK-1", "123456", 10000)
        assert not repetida.ok
        assert repetida.ya_capturada

    def test_captura_falla(self):
        creada = self._crear()
        FakeGateway.configurar(capturar_falla=True)
        with pytest.raises(ErrorPasarela):
            FakeGateway().capturar(creada.token, "SK-1", "123456", 10000)

    def test_reembolsar(self):
        creada = self._crear()
        resultado = FakeGateway().reembolsar(creada.token, 5000)
        assert resultado.ok
        assert resultado.estado == "REFUNDED"
        assert resultado.monto == 5000

    def test_reembolso_falla(self):
        FakeGateway.configurar(reembolsar_falla=True)
        creada = self._crear()
        with pytest.raises(ErrorPasarela):
            FakeGateway().reembolsar(creada.token, 5000)

    def test_estado(self):
        creada = self._crear()
        resultado = FakeGateway().estado(creada.token)
        assert resultado.ok
        assert resultado.estado == "INITIALIZED"

    def test_configuracion_desconocida(self):
        with pytest.raises(ValueError):
            FakeGateway.configurar(no_existe=True)
