import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.pagos import estados, services
from apps.pagos.gateway.base import ErrorPasarela
from apps.pagos.gateway.fake import FakeGateway
from apps.pagos.models import Pago


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


def _registrar_en_fake(pago):
    FakeGateway._transacciones[pago.token] = {
        "buy_order": pago.buy_order,
        "session_id": pago.session_id,
        "monto": pago.monto_total,
        "return_url": "",
        "estado": "AUTHORIZED",
        "capturada": False,
    }
    return pago


def _pago_retenido(reserva, **overrides):
    token = f"FAKE-{uuid.uuid4().hex}"
    pago = _pago(reserva, estado=estados.RETENIDO, token=token, **overrides)
    return _registrar_en_fake(pago)


def _pago_autorizado(reserva, **overrides):
    token = f"FAKE-{uuid.uuid4().hex}"
    pago = _pago(reserva, estado=estados.AUTORIZADO, token=token, **overrides)
    return _registrar_en_fake(pago)


def _iniciar_y_confirmar(reserva, **fake_config):
    FakeGateway.configurar(**fake_config)
    inicio = services.iniciar_pago(reserva)
    return services.confirmar_pago(inicio.token)


@pytest.mark.django_db
@pytest.mark.pagos
class TestIniciarPago:
    def test_crea_pago_con_token_y_montos(self, reserva_pendiente):
        inicio = services.iniciar_pago(reserva_pendiente)

        assert inicio.token
        assert inicio.token.startswith("FAKE-")
        pago = inicio.pago
        assert pago.estado == estados.INICIADO
        assert pago.pasarela == "fake"
        assert pago.monto_total == 150000
        assert pago.monto_comision == 15000
        assert pago.monto_neto == 135000
        assert pago.expira_en > timezone.now()
        assert pago.eventos.filter(a_estado=estados.INICIADO).exists()

    def test_es_idempotente_mientras_el_pago_esta_vigente(self, reserva_pendiente):
        primero = services.iniciar_pago(reserva_pendiente)
        segundo = services.iniciar_pago(reserva_pendiente)

        assert segundo.pago.pk == primero.pago.pk
        assert segundo.token == primero.token
        assert Pago.objects.filter(reserva=reserva_pendiente).count() == 1

    def test_no_crea_otro_si_hay_pago_retenido(self, reserva_pendiente):
        _pago(reserva_pendiente, estado=estados.RETENIDO)
        with pytest.raises(ValidationError):
            services.iniciar_pago(reserva_pendiente)

    def test_falla_de_creacion_deja_pago_rechazado(self, reserva_pendiente):
        FakeGateway.configurar(crear_falla=True)
        with pytest.raises(ValidationError):
            services.iniciar_pago(reserva_pendiente)
        pago = Pago.objects.get(reserva=reserva_pendiente)
        assert pago.estado == estados.RECHAZADO


@pytest.mark.django_db
@pytest.mark.pagos
class TestConfirmarPago:
    def test_credito_queda_autorizado_sin_capturar(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente)

        assert pago.estado == estados.AUTORIZADO
        assert pago.capturado_en_autorizacion is False
        assert pago.codigo_autorizacion == "123456"
        assert pago.tipo_pago == "VC"
        assert pago.tarjeta_ultimos4 == "6623"
        assert pago.respuesta_pasarela["card_number"] == "***"
        assert pago.respuesta_pasarela["token"] == "***"

    def test_debito_queda_retenido_y_marcado_capturado(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente, tipo_pago="VD")

        assert pago.estado == estados.RETENIDO
        assert pago.capturado_en_autorizacion is True

    def test_confirmar_es_idempotente(self, reserva_pendiente):
        inicio = services.iniciar_pago(reserva_pendiente)
        primero = services.confirmar_pago(inicio.token)
        eventos = primero.eventos.count()
        segundo = services.confirmar_pago(inicio.token)

        assert segundo.pk == primero.pk
        assert segundo.estado == estados.AUTORIZADO
        assert segundo.eventos.count() == eventos

    def test_rechazo_de_tarjeta(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente, modo="rechazar")

        assert pago.estado == estados.RECHAZADO
        assert pago.codigo_respuesta == 1

    def test_abandono_se_trata_como_rechazo(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente, modo="abandonar")
        assert pago.estado == estados.RECHAZADO

    def test_expirado(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente, modo="expirado")
        assert pago.estado == estados.EXPIRADO

    def test_monto_distinto_deja_revision_manual_y_revierte(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente, monto_alterado=1)

        assert pago.estado == estados.REVISION_MANUAL
        assert FakeGateway.transaccion(pago.token)["estado"] == "REFUNDED"

    def test_error_de_red_y_estado_deja_revision_manual(self, reserva_pendiente):
        inicio = services.iniciar_pago(reserva_pendiente)
        FakeGateway.configurar(modo="fallar")
        pago = services.confirmar_pago(inicio.token)
        assert pago.estado == estados.REVISION_MANUAL

    def test_token_desconocido(self):
        with pytest.raises(ValidationError):
            services.confirmar_pago("no-existe")


@pytest.mark.django_db
@pytest.mark.pagos
class TestCapturarLiberar:
    def test_captura_credito(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente)
        capturado = services.capturar_pago(pago)

        assert capturado.estado == estados.RETENIDO
        assert capturado.capturado_en is not None

    def test_captura_es_idempotente_si_ya_esta_retenido(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente)
        services.capturar_pago(pago)
        eventos = pago.eventos.count()
        repetido = services.capturar_pago(pago)
        assert repetido.estado == estados.RETENIDO
        assert repetido.eventos.count() == eventos

    def test_falla_de_captura_vuelve_a_autorizado(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente)
        FakeGateway.configurar(capturar_falla=True)

        with pytest.raises(ErrorPasarela):
            services.capturar_pago(pago)

        pago.refresh_from_db()
        assert pago.estado == estados.AUTORIZADO

    def test_captura_previa_se_concilia(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente)
        FakeGateway.configurar(ya_capturada=True)
        conciliado = FakeGateway.transaccion(pago.token)
        conciliado["estado"] = "CAPTURED"

        capturado = services.capturar_pago(pago)
        assert capturado.estado == estados.RETENIDO

    def test_liberar_pago_retenido(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.RETENIDO)
        liberado = services.liberar_pago(pago)
        assert liberado.estado == estados.LIBERADO
        assert liberado.liberado_en is not None

    def test_no_liberar_pago_autorizado(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.AUTORIZADO)
        with pytest.raises(ValidationError):
            services.liberar_pago(pago)


@pytest.mark.django_db
@pytest.mark.pagos
class TestReembolsos:
    def test_reembolso_total(self, reserva_pendiente):
        pago = _pago_retenido(reserva_pendiente)
        reembolsado = services.reembolsar_pago(pago)

        assert reembolsado.estado == estados.REEMBOLSADO
        assert reembolsado.monto_reembolsado == 150000

    def test_reembolso_parcial_90(self, reserva_pendiente):
        pago = _pago_retenido(reserva_pendiente)
        reembolsado = services.reembolsar_pago(pago, porcentaje=90)

        assert reembolsado.monto_reembolsado == 135000
        assert reembolsado.estado == estados.REEMBOLSADO

    def test_reembolso_redondea_half_up(self, reserva_pendiente):
        reserva_pendiente.precio_acordado = 12345
        reserva_pendiente.save(update_fields=["precio_acordado"])
        pago = _pago_retenido(reserva_pendiente)
        reembolsado = services.reembolsar_pago(pago, porcentaje=90)
        assert reembolsado.monto_reembolsado == 11111

    def test_no_reembolsar_pago_autorizado(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.AUTORIZADO)
        with pytest.raises(ValidationError):
            services.reembolsar_pago(pago)

    def test_falla_de_reembolso_deja_revision_manual(self, reserva_pendiente):
        pago = _pago_retenido(reserva_pendiente)
        FakeGateway.configurar(reembolsar_falla=True)

        with pytest.raises(ErrorPasarela):
            services.reembolsar_pago(pago)

        pago.refresh_from_db()
        assert pago.estado == estados.REVISION_MANUAL

    def test_cancelar_autorizacion(self, reserva_pendiente):
        pago = _iniciar_y_confirmar(reserva_pendiente)
        assert pago.estado == estados.AUTORIZADO

        cancelado = services.cancelar_pago(pago)
        assert cancelado.estado == estados.CANCELADO


@pytest.mark.django_db
@pytest.mark.pagos
class TestExpiracion:
    def test_expira_pagos_iniciados_vencidos(self, reserva_pendiente):
        vencido = _pago(
            reserva_pendiente,
            buy_order="SK-vencido",
            session_id="s-1",
            expira_en=timezone.now() - timedelta(minutes=1),
        )
        vigente = _pago(
            reserva_pendiente,
            buy_order="SK-vigente",
            session_id="s-2",
            expira_en=timezone.now() + timedelta(minutes=1),
        )

        total = services.expirar_pagos_vencidos()

        vencido.refresh_from_db()
        vigente.refresh_from_db()
        assert total == 1
        assert vencido.estado == estados.EXPIRADO
        assert vigente.estado == estados.INICIADO

    def test_no_expira_pago_retenido(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.RETENIDO)
        with pytest.raises(ValidationError):
            services.expirar_pago(pago)


@pytest.mark.django_db
@pytest.mark.pagos
class TestCasosBorde:
    def test_pago_vigente_encuentra_el_retenido(self, reserva_pendiente):
        pago = _pago_retenido(reserva_pendiente)
        assert services.pago_vigente(reserva_pendiente).pk == pago.pk

    def test_calcular_reembolso_rechaza_porcentaje_invalido(self):
        with pytest.raises(ValidationError):
            services.calcular_reembolso(10000, 101)

    def test_iniciar_reemplaza_pago_iniciado_vencido(self, reserva_pendiente):
        viejo = _pago(
            reserva_pendiente,
            buy_order="SK-viejo",
            session_id="s-viejo",
            expira_en=timezone.now() - timedelta(minutes=1),
        )
        nuevo = services.iniciar_pago(reserva_pendiente)

        viejo.refresh_from_db()
        assert viejo.estado == estados.EXPIRADO
        assert nuevo.pago.pk != viejo.pk
        assert Pago.objects.filter(reserva=reserva_pendiente).count() == 2

    def test_no_capturar_pago_iniciado(self, reserva_pendiente):
        pago = _pago(reserva_pendiente)
        with pytest.raises(ValidationError):
            services.capturar_pago(pago)

    def test_liberar_pago_es_idempotente(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.LIBERADO)
        assert services.liberar_pago(pago).estado == estados.LIBERADO

    def test_reembolsar_pago_ya_reembolsado_es_idempotente(self, reserva_pendiente):
        pago = _pago_retenido(reserva_pendiente)
        services.reembolsar_pago(pago)
        repetido = services.reembolsar_pago(pago)
        assert repetido.estado == estados.REEMBOLSADO
        assert repetido.monto_reembolsado == 150000

    def test_reembolsar_monto_invalido(self, reserva_pendiente):
        pago = _pago_retenido(reserva_pendiente)
        with pytest.raises(ValidationError):
            services.reembolsar_pago(pago, monto=0)

    def test_cancelar_pago_ya_cancelado_es_idempotente(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.CANCELADO)
        assert services.cancelar_pago(pago).estado == estados.CANCELADO

    def test_no_cancelar_pago_iniciado(self, reserva_pendiente):
        pago = _pago(reserva_pendiente)
        with pytest.raises(ValidationError):
            services.cancelar_pago(pago)

    def test_falla_de_revocacion_deja_revision_manual(self, reserva_pendiente):
        pago = _pago_autorizado(reserva_pendiente)
        FakeGateway.configurar(reembolsar_falla=True)
        with pytest.raises(ErrorPasarela):
            services.cancelar_pago(pago)
        pago.refresh_from_db()
        assert pago.estado == estados.REVISION_MANUAL

    def test_revocacion_rechazada_deja_revision_manual(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.AUTORIZADO, token="FAKE-otro")
        with pytest.raises(ErrorPasarela):
            services.cancelar_pago(pago)
        pago.refresh_from_db()
        assert pago.estado == estados.REVISION_MANUAL

    def test_expirar_pago_es_idempotente(self, reserva_pendiente):
        pago = _pago(reserva_pendiente, estado=estados.EXPIRADO)
        assert services.expirar_pago(pago).estado == estados.EXPIRADO
