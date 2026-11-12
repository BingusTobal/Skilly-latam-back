"""R18: auto-liberación a los 5 días y guard de disputa."""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.pagos import estados
from apps.pagos import services as pagos_services
from apps.pagos.models import Pago
from apps.reservas import services
from apps.reservas.models import Disputa, EventoReserva, Reserva


def _entregada(reserva):
    services.aceptar(reserva)
    services.marcar_entregado(reserva)
    return reserva


def _pago(reserva):
    return Pago.objects.get(reserva=reserva)


@pytest.mark.django_db
@pytest.mark.reservas
class TestLiberacionAutomatica:
    def test_libera_al_vencer_el_plazo(self, reserva_pendiente):
        _entregada(reserva_pendiente)

        total = services.liberar_entregas_vencidas(
            ahora=timezone.now() + timedelta(days=6)
        )

        assert total == 1
        reserva_pendiente.refresh_from_db()
        assert reserva_pendiente.estado == Reserva.ESTADO_FINALIZADA
        assert reserva_pendiente.confirmada_en is not None

        pago = _pago(reserva_pendiente)
        assert pago.estado == estados.LIBERADO
        assert pago.liberado_en is not None

        evento = reserva_pendiente.eventos.filter(
            tipo=EventoReserva.TIPO_CONFIRMADA
        ).last()
        assert "plazo" in evento.detalle.lower()

    def test_no_libera_antes_del_plazo(self, reserva_pendiente):
        _entregada(reserva_pendiente)

        total = services.liberar_entregas_vencidas(
            ahora=timezone.now() + timedelta(days=4)
        )

        assert total == 0
        reserva_pendiente.refresh_from_db()
        assert reserva_pendiente.estado == Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR
        assert _pago(reserva_pendiente).estado == estados.RETENIDO

    def test_no_libera_si_hay_disputa_abierta(self, reserva_pendiente):
        _entregada(reserva_pendiente)
        services.reportar_problema(
            reserva_pendiente, motivo="No cumplió", descripcion="Faltó la mitad."
        )

        total = services.liberar_entregas_vencidas(
            ahora=timezone.now() + timedelta(days=6)
        )

        assert total == 0
        reserva_pendiente.refresh_from_db()
        assert reserva_pendiente.estado == Reserva.ESTADO_CON_DISPUTA
        assert _pago(reserva_pendiente).estado == estados.RETENIDO

    def test_confirmar_entrega_con_disputa_abierta_falla(self, reserva_pendiente):
        _entregada(reserva_pendiente)
        Disputa.objects.create(
            reserva=reserva_pendiente,
            motivo="Reclamo en revisión",
            estado=Disputa.ESTADO_EN_REVISION,
        )

        with pytest.raises(ValidationError):
            services.confirmar_entrega(reserva_pendiente)

        assert _pago(reserva_pendiente).estado == estados.RETENIDO

    def test_liberar_pago_con_disputa_abierta_falla(self, reserva_pendiente):
        _entregada(reserva_pendiente)
        Disputa.objects.create(
            reserva=reserva_pendiente,
            motivo="Reclamo en revisión",
            estado=Disputa.ESTADO_ABIERTA,
        )

        with pytest.raises(ValidationError):
            pagos_services.liberar_pago(_pago(reserva_pendiente))

        assert _pago(reserva_pendiente).estado == estados.RETENIDO
