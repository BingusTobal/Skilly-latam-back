import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.pagos import estados
from apps.pagos.models import Pago, PagoEvento
from apps.pagos.estados import TransicionInvalida
from apps.pagos.seguridad import sanear


def _pago(reserva, **overrides):
    montos = Pago.calcular_montos(reserva)
    datos = {
        "reserva": reserva,
        "buy_order": f"SK{reserva.pk}{uuid.uuid4().hex}"[:26],
        "session_id": f"rsv-{reserva.pk}-{uuid.uuid4().hex}"[:61],
        **montos,
    }
    datos.update(overrides)
    return Pago.objects.create(**datos)


@pytest.mark.django_db
@pytest.mark.pagos
class TestMontos:
    def test_neto_mas_comision_igual_total(self, reserva_pendiente):
        montos = Pago.calcular_montos(reserva_pendiente)
        assert montos == {
            "monto_total": 150000,
            "monto_comision": 15000,
            "monto_neto": 135000,
        }
        assert montos["monto_neto"] + montos["monto_comision"] == montos["monto_total"]

    def test_redondeo_comercial_half_up(self, reserva_pendiente):
        reserva_pendiente.precio_acordado = Decimal("12345.00")
        reserva_pendiente.tasa_comision = Decimal("0.100")
        reserva_pendiente.save(update_fields=["precio_acordado", "tasa_comision"])

        montos = Pago.calcular_montos(reserva_pendiente)
        # 12345 * 10% = 1234,5 => 1235 (ROUND_HALF_UP)
        assert montos["monto_comision"] == 1235
        assert montos["monto_neto"] == 11110

    def test_rechaza_precio_con_decimales(self, reserva_pendiente):
        reserva_pendiente.precio_acordado = Decimal("10000.50")
        reserva_pendiente.save(update_fields=["precio_acordado"])
        with pytest.raises(ValidationError):
            Pago.calcular_montos(reserva_pendiente)

    def test_clean_valida_suma_de_montos(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, monto_neto=1)
        with pytest.raises(ValidationError):
            pago.full_clean()


@pytest.mark.django_db
@pytest.mark.pagos
class TestMaquinaDeEstados:
    def test_transicion_valida_registra_evento(self, reserva_pendiente):
        pago = _pago(reserva_pendiente)
        evento = pago.pasar_a(
            estados.AUTORIZADO,
            actor=Pago.ACTOR_PROFESIONAL,
            motivo="Autorización de prueba.",
            datos={"token": "secreto", "ok": True},
        )
        pago.refresh_from_db()
        assert pago.estado == estados.AUTORIZADO
        assert pago.autorizado_en is not None
        assert evento.de_estado == estados.INICIADO
        assert evento.a_estado == estados.AUTORIZADO
        assert evento.datos["token"] == "***"
        assert evento.datos["ok"] is True

    def test_transicion_invalida(self, reserva_pendiente):
        pago = _pago(reserva_pendiente)
        with pytest.raises(TransicionInvalida):
            pago.pasar_a(estados.LIBERADO)
        pago.refresh_from_db()
        assert pago.estado == estados.INICIADO

    def test_evento_es_inmutable(self, reserva_pendiente):
        pago = _pago(reserva_pendiente)
        evento = pago.pasar_a(estados.AUTORIZADO)
        evento.motivo = "cambiado"
        with pytest.raises(ValidationError):
            evento.save()
        with pytest.raises(ValidationError):
            evento.delete()

    def test_liberado_solo_puede_reembolsarse(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.RETENIDO)
        pago.pasar_a(estados.LIBERADO)
        with pytest.raises(TransicionInvalida):
            pago.pasar_a(estados.CANCELADO)


@pytest.mark.pagos
class TestSeguridad:
    def test_sanear_quita_datos_sensibles_en_cascada(self):
        datos = {
            "token": "abc",
            "tarjeta": {"card_number": "4051885600446623", "cvv": "123"},
            "lista": [{"token_ws": "xyz"}],
            "monto": 1000,
        }
        limpio = sanear(datos)
        assert limpio["token"] == "***"
        assert limpio["tarjeta"]["card_number"] == "***"
        assert limpio["tarjeta"]["cvv"] == "***"
        assert limpio["lista"][0]["token_ws"] == "***"
        assert limpio["monto"] == 1000
