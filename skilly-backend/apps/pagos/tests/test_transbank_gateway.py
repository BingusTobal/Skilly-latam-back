"""Pruebas del adaptador Transbank sin llamadas de red (SDK mockeado)."""
import pytest
import requests
from transbank.common.integration_type import IntegrationType
from transbank.error.transaction_capture_error import TransactionCaptureError
from transbank.error.transbank_error import TransbankError

from apps.pagos.gateway.base import ErrorPasarela
from apps.pagos.gateway.transbank import TransbankGateway


class TransaccionFalsa:
    def __init__(self, *, crear=None, confirmar=None, estado=None, capturar=None, reembolsar=None):
        self._crear = crear
        self._confirmar = confirmar
        self._estado = estado
        self._capturar = capturar
        self._reembolsar = reembolsar

    def create(self, buy_order, session_id, monto, return_url):
        return self._crear(buy_order, session_id, monto, return_url)

    def commit(self, token):
        return self._confirmar(token)

    def status(self, token):
        return self._estado(token)

    def capture(self, token, buy_order, codigo_autorizacion, monto):
        return self._capturar(token, buy_order, codigo_autorizacion, monto)

    def refund(self, token, monto):
        return self._reembolsar(token, monto)


def _gateway(monkeypatch, transaccion):
    gateway = TransbankGateway()
    monkeypatch.setattr(gateway, "_transaction", lambda: transaccion)
    return gateway


def _commit_aprobado(**extra):
    datos = {
        "status": "AUTHORIZED",
        "response_code": 0,
        "amount": 150000,
        "buy_order": "SK1abc",
        "session_id": "rsv-1-abc",
        "authorization_code": "123456",
        "payment_type_code": "VC",
        "installments_number": 0,
        "card_detail": {"card_number": "6623"},
    }
    datos.update(extra)
    return datos


@pytest.mark.pagos
class TestCrear:
    def test_crear_ok(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                crear=lambda *a: {
                    "token": "TOKEN-1",
                    "url": "https://webpay3gint.transbank.cl/webpayserver/initTransaction",
                }
            ),
        )
        resultado = gateway.crear("SK1abc", "rsv-1", 150000, "http://localhost/retorno")

        assert resultado.ok is True
        assert resultado.token == "TOKEN-1"
        assert resultado.url.startswith("https://webpay3gint.transbank.cl/")

    def test_crear_sin_token_es_error(self, monkeypatch):
        gateway = _gateway(
            monkeypatch, TransaccionFalsa(crear=lambda *a: {"url": "https://x"})
        )
        resultado = gateway.crear("SK1abc", "rsv-1", 150000, "http://localhost/retorno")
        assert resultado.ok is False
        assert resultado.error

    def test_crear_error_sdk(self, monkeypatch):
        def fallar(*args):
            raise TransbankError("falló create", 500)

        gateway = _gateway(monkeypatch, TransaccionFalsa(crear=fallar))
        with pytest.raises(ErrorPasarela, match="falló create"):
            gateway.crear("SK1abc", "rsv-1", 150000, "http://localhost/retorno")

    def test_crear_error_de_red(self, monkeypatch):
        def fallar(*args):
            raise requests.ConnectionError("sin red")

        gateway = _gateway(monkeypatch, TransaccionFalsa(crear=fallar))
        with pytest.raises(ErrorPasarela, match="No se pudo comunicar"):
            gateway.crear("SK1abc", "rsv-1", 150000, "http://localhost/retorno")


@pytest.mark.pagos
class TestConfirmarYEstado:
    def test_confirmar_aprobado(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(confirmar=lambda token: _commit_aprobado()),
        )
        resultado = gateway.confirmar("TOKEN-1")

        assert resultado.ok is True
        assert resultado.estado == "AUTHORIZED"
        assert resultado.monto == 150000
        assert resultado.codigo_autorizacion == "123456"
        assert resultado.tipo_pago == "VC"
        assert resultado.tarjeta_ultimos4 == "6623"
        assert resultado.respuesta["card_detail"]["card_number"] == "***"

    def test_confirmar_rechazado(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                confirmar=lambda token: _commit_aprobado(
                    status="FAILED", response_code=1, authorization_code=""
                )
            ),
        )
        resultado = gateway.confirmar("TOKEN-1")

        assert resultado.ok is False
        assert resultado.estado == "REJECTED"
        assert resultado.codigo_respuesta == 1
        assert "código 1" in resultado.error

    def test_confirmar_capturado(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                confirmar=lambda token: _commit_aprobado(status="CAPTURED")
            ),
        )
        resultado = gateway.confirmar("TOKEN-1")
        assert resultado.ok is True
        assert resultado.estado == "CAPTURED"

    def test_estado_fallido_sigue_siendo_consulta_ok(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                estado=lambda token: _commit_aprobado(
                    status="FAILED", response_code=1
                )
            ),
        )
        resultado = gateway.estado("TOKEN-1")

        assert resultado.ok is True
        assert resultado.estado == "REJECTED"

    def test_estado_inicializado(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                estado=lambda token: {
                    "status": "INITIALIZED",
                    "response_code": 0,
                    "amount": 150000,
                }
            ),
        )
        resultado = gateway.estado("TOKEN-1")
        assert resultado.ok is True
        assert resultado.estado == "INITIALIZED"

    def test_estado_error_sdk(self, monkeypatch):
        def fallar(token):
            raise TransbankError("token inválido", 404)

        gateway = _gateway(monkeypatch, TransaccionFalsa(estado=fallar))
        with pytest.raises(ErrorPasarela, match="token inválido"):
            gateway.estado("TOKEN-1")


@pytest.mark.pagos
class TestCapturarYReembolsar:
    def test_capturar_ok(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                capturar=lambda *a: {
                    "response_code": 0,
                    "captured_amount": 150000,
                    "authorization_code": "123456",
                }
            ),
        )
        resultado = gateway.capturar("TOKEN-1", "SK1abc", "123456", 150000)

        assert resultado.ok is True
        assert resultado.estado == "CAPTURED"
        assert resultado.monto == 150000
        assert resultado.codigo_autorizacion == "123456"

    def test_capturar_ya_realizada(self, monkeypatch):
        def fallar(*args):
            raise TransactionCaptureError("Transaction already captured", 422)

        gateway = _gateway(monkeypatch, TransaccionFalsa(capturar=fallar))
        resultado = gateway.capturar("TOKEN-1", "SK1abc", "123456", 150000)

        assert resultado.ok is False
        assert resultado.ya_capturada is True
        assert resultado.estado == "CAPTURED"

    def test_capturar_otro_error(self, monkeypatch):
        def fallar(*args):
            raise TransactionCaptureError("captura rechazada", 422)

        gateway = _gateway(monkeypatch, TransaccionFalsa(capturar=fallar))
        with pytest.raises(ErrorPasarela, match="captura rechazada"):
            gateway.capturar("TOKEN-1", "SK1abc", "123456", 150000)

    def test_reembolsar_ok(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                reembolsar=lambda *a: {
                    "response_code": 0,
                    "nullified_amount": 150000,
                    "balance": 0,
                }
            ),
        )
        resultado = gateway.reembolsar("TOKEN-1", 150000)

        assert resultado.ok is True
        assert resultado.estado == "REFUNDED"
        assert resultado.monto == 150000

    def test_reembolsar_rechazado(self, monkeypatch):
        gateway = _gateway(
            monkeypatch,
            TransaccionFalsa(
                reembolsar=lambda *a: {
                    "response_code": 2,
                    "nullified_amount": 0,
                }
            ),
        )
        resultado = gateway.reembolsar("TOKEN-1", 150000)

        assert resultado.ok is False
        assert "código 2" in resultado.error


@pytest.mark.pagos
class TestConfiguracionSdk:
    def test_integracion_usa_entorno_test(self, monkeypatch, settings):
        settings.TRANSBANK_ENV = "integration"
        settings.TRANSBANK_COMMERCE_CODE = "597055555540"
        settings.TRANSBANK_API_KEY_SECRET = "secreto"
        settings.TRANSBANK_TIMEOUT = 7
        capturado = {}

        class TransactionFalsa:
            def __init__(self, options):
                capturado["options"] = options

        monkeypatch.setattr(
            "apps.pagos.gateway.transbank.Transaction", TransactionFalsa
        )
        TransbankGateway()._transaction()

        assert capturado["options"].integration_type == IntegrationType.TEST
        assert capturado["options"].timeout == 7

    def test_produccion_usa_entorno_live(self, monkeypatch, settings):
        settings.TRANSBANK_ENV = "production"
        settings.TRANSBANK_COMMERCE_CODE = "597012345678"
        settings.TRANSBANK_API_KEY_SECRET = "secreto"
        settings.TRANSBANK_TIMEOUT = 7
        capturado = {}

        class TransactionFalsa:
            def __init__(self, options):
                capturado["options"] = options

        monkeypatch.setattr(
            "apps.pagos.gateway.transbank.Transaction", TransactionFalsa
        )
        TransbankGateway()._transaction()

        assert capturado["options"].integration_type == IntegrationType.LIVE
