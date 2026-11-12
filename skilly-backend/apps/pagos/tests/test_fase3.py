"""Flujos de captura, reembolso, expiración y conciliación (Fase 3)."""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.pagos import estados, services
from apps.pagos.gateway.fake import FakeGateway
from apps.pagos.models import Pago
from apps.pagos.tasks import (
    tarea_alertar_autorizaciones_por_vencer,
    tarea_conciliar_pagos,
    tarea_expirar_pagos_pendientes,
)
from apps.reservas import services as reserva_services
from apps.reservas.models import Reserva


def _pagar(reserva, **config):
    FakeGateway.configurar(**config)
    inicio = services.iniciar_pago(reserva)
    return services.confirmar_pago(inicio.token)


def _envejecer(pago, minutos=10):
    Pago.objects.filter(pk=pago.pk).update(
        actualizado_en=timezone.now() - timedelta(minutes=minutos)
    )


@pytest.mark.django_db
@pytest.mark.pagos
class TestConfirmacionYDatosDeReserva:
    def test_iniciar_exige_reserva_pendiente_de_pago(self, reserva_pendiente):
        with pytest.raises(ValidationError):
            services.iniciar_pago(reserva_pendiente)

    def test_confirmar_activa_la_reserva_y_arranca_el_plazo(self, reserva_por_pagar):
        pago = _pagar(reserva_por_pagar)

        reserva_por_pagar.refresh_from_db()
        assert pago.estado == estados.AUTORIZADO
        assert reserva_por_pagar.estado == Reserva.ESTADO_PENDIENTE_ACEPTACION
        assert reserva_por_pagar.expira_en is not None
        assert reserva_por_pagar.eventos.filter(
            tipo="pago_confirmado"
        ).exists()

    def test_rechazo_cancela_la_reserva_y_libera_el_horario(self, reserva_por_pagar):
        pago = _pagar(reserva_por_pagar, modo="rechazar")

        reserva_por_pagar.refresh_from_db()
        assert pago.estado == estados.RECHAZADO
        assert reserva_por_pagar.estado == Reserva.ESTADO_CANCELADA

    def test_vencimiento_cancela_la_reserva(self, reserva_por_pagar):
        inicio = services.iniciar_pago(reserva_por_pagar)
        Pago.objects.filter(pk=inicio.pago.pk).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )

        assert services.expirar_pagos_vencidos() == 1

        inicio.pago.refresh_from_db()
        reserva_por_pagar.refresh_from_db()
        assert inicio.pago.estado == estados.EXPIRADO
        assert reserva_por_pagar.estado == Reserva.ESTADO_CANCELADA


@pytest.mark.django_db
@pytest.mark.pagos
class TestCapturaYLiberacion:
    def test_aceptar_captura_el_pago_autorizado(self, reserva_por_pagar):
        pago = _pagar(reserva_por_pagar)

        reserva_services.aceptar(reserva_por_pagar)

        pago.refresh_from_db()
        reserva_por_pagar.refresh_from_db()
        assert pago.estado == estados.RETENIDO
        assert FakeGateway.transaccion(pago.token)["capturada"] is True
        assert reserva_por_pagar.estado == Reserva.ESTADO_EN_CURSO

    def test_confirmar_entrega_libera_el_pago(self, reserva_pendiente):
        reserva_services.aceptar(reserva_pendiente)
        reserva_services.marcar_entregado(reserva_pendiente)
        reserva_services.confirmar_entrega(reserva_pendiente)

        pago = Pago.objects.get(reserva=reserva_pendiente, estado=estados.LIBERADO)
        assert pago.liberado_en is not None
        assert reserva_pendiente.estado == Reserva.ESTADO_FINALIZADA

    def test_rechazar_reembolsa_el_pago_retenido(self, reserva_pendiente):
        reserva_services.rechazar(reserva_pendiente, motivo="No puedo.")

        pago = Pago.objects.get(reserva=reserva_pendiente)
        assert pago.estado == estados.REEMBOLSADO
        assert pago.monto_reembolsado == pago.monto_total
        assert reserva_pendiente.estado == Reserva.ESTADO_CANCELADA


@pytest.mark.django_db
@pytest.mark.pagos
class TestCancelacionYVencimiento:
    def test_cancelar_autorizacion_sin_captura(self, reserva_por_pagar):
        pago = _pagar(reserva_por_pagar)

        reserva_services.cancelar(reserva_por_pagar)

        pago.refresh_from_db()
        assert pago.estado == estados.CANCELADO
        assert reserva_por_pagar.estado == Reserva.ESTADO_CANCELADA

    def test_cancelar_pago_retenido_aplica_porcentaje(
        self, reserva_pendiente, monkeypatch
    ):
        monkeypatch.setattr(
            reserva_services, "porcentaje_reembolso", lambda reserva, ahora=None: 90
        )

        reserva_services.cancelar(reserva_pendiente)

        pago = Pago.objects.get(reserva=reserva_pendiente)
        assert pago.estado == estados.REEMBOLSADO
        assert pago.monto_reembolsado == services.calcular_reembolso(
            pago.monto_total, 90
        )

    def test_vencer_reembolsa_el_pago_retenido(self, reserva_pendiente):
        reserva_pendiente.expira_en = timezone.now() - timedelta(minutes=1)
        reserva_pendiente.save(update_fields=["expira_en"])

        assert reserva_services.expirar_vencidas() == 1

        pago = Pago.objects.get(reserva=reserva_pendiente)
        reserva_pendiente.refresh_from_db()
        assert pago.estado == estados.REEMBOLSADO
        assert reserva_pendiente.estado == Reserva.ESTADO_VENCIDA

    def test_vencer_cancela_autorizacion(self, reserva_por_pagar):
        pago = _pagar(reserva_por_pagar)
        reserva_por_pagar.refresh_from_db()
        reserva_por_pagar.expira_en = timezone.now() - timedelta(minutes=1)
        reserva_por_pagar.save(update_fields=["expira_en"])

        assert reserva_services.expirar_vencidas() == 1

        pago.refresh_from_db()
        assert pago.estado == estados.CANCELADO


@pytest.mark.django_db
@pytest.mark.pagos
class TestConciliacionYAlertas:
    def test_conciliar_iniciado_autorizado_activa_la_reserva(
        self, reserva_por_pagar
    ):
        inicio = services.iniciar_pago(reserva_por_pagar)
        FakeGateway._transacciones[inicio.token]["estado"] = "AUTHORIZED"
        _envejecer(inicio.pago)

        assert services.conciliar_pagos() == 1

        inicio.pago.refresh_from_db()
        reserva_por_pagar.refresh_from_db()
        assert inicio.pago.estado == estados.AUTORIZADO
        assert reserva_por_pagar.estado == Reserva.ESTADO_PENDIENTE_ACEPTACION

    def test_conciliar_capturando_confirmado_pasa_a_retenido(
        self, reserva_por_pagar
    ):
        pago = _pagar(reserva_por_pagar)
        pago.pasar_a(estados.CAPTURANDO)
        FakeGateway._transacciones[pago.token]["estado"] = "CAPTURED"
        _envejecer(pago)

        assert services.conciliar_pagos() == 1

        pago.refresh_from_db()
        assert pago.estado == estados.RETENIDO

    def test_conciliar_capturando_sin_captura_revierte(self, reserva_por_pagar):
        pago = _pagar(reserva_por_pagar)
        pago.pasar_a(estados.CAPTURANDO)
        FakeGateway._transacciones[pago.token]["estado"] = "AUTHORIZED"
        _envejecer(pago)

        assert services.conciliar_pagos() == 1

        pago.refresh_from_db()
        assert pago.estado == estados.AUTORIZADO

    def test_conciliar_rechazado_cancela_la_reserva(self, reserva_por_pagar):
        inicio = services.iniciar_pago(reserva_por_pagar)
        FakeGateway._transacciones[inicio.token]["estado"] = "REJECTED"
        _envejecer(inicio.pago)

        assert services.conciliar_pagos() == 1

        inicio.pago.refresh_from_db()
        reserva_por_pagar.refresh_from_db()
        assert inicio.pago.estado == estados.RECHAZADO
        assert reserva_por_pagar.estado == Reserva.ESTADO_CANCELADA

    def test_alerta_autorizaciones_proximas_a_vencer(
        self, reserva_por_pagar, caplog
    ):
        pago = _pagar(reserva_por_pagar)
        pago.autorizado_en = timezone.now() - timedelta(days=7)
        pago.save(update_fields=["autorizado_en"])

        with caplog.at_level("WARNING"):
            total = services.alertar_autorizaciones_por_vencer()

        assert total == 1
        assert "próxima a vencer" in caplog.text

    def test_tareas_celery_llaman_a_los_servicios(self, reserva_por_pagar, monkeypatch):
        monkeypatch.setattr(
            "apps.pagos.tasks.expirar_pagos_vencidos", lambda: 2
        )
        monkeypatch.setattr("apps.pagos.tasks.conciliar_pagos", lambda: 3)
        monkeypatch.setattr(
            "apps.pagos.tasks.alertar_autorizaciones_por_vencer", lambda: 4
        )

        assert tarea_expirar_pagos_pendientes() == 2
        assert tarea_conciliar_pagos() == 3
        assert tarea_alertar_autorizaciones_por_vencer() == 4
