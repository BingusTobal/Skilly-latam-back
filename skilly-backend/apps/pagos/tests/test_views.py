"""
Tests de la API de pagos: iniciar, retorno de Webpay y consulta de estado.
"""
from urllib.parse import parse_qs, urlsplit

import pytest
from rest_framework.test import APIClient

from apps.pagos import estados
from apps.pagos.gateway.fake import FakeGateway
from apps.pagos.models import Pago
from apps.reservas.models import Reserva

URL_INICIAR = "/api/reservas/{}/pago/iniciar/"
URL_RETORNO = "/api/pagos/transbank/retorno/"
URL_ESTADO = "/api/pagos/{}/estado/"


def _iniciar_por_token(client, reserva):
    token = reserva.generar_token()
    resp = client.post(f"{URL_INICIAR.format(reserva.pk)}?token={token}")
    assert resp.status_code == 200, resp.data
    return resp.data


@pytest.mark.django_db
class TestIniciarPagoView:
    def test_invitado_con_token_puede_iniciar(self, anon_client, reserva_por_pagar):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        assert datos["url"].startswith("https://fake.webpay.cl/")
        assert datos["token"].startswith("FAKE-")
        pago = Pago.objects.get(referencia_publica=datos["referencia_publica"])
        assert pago.estado == estados.INICIADO
        assert pago.monto_total == int(reserva_por_pagar.precio_acordado)

    def test_duenio_organizacion_puede_iniciar_sin_token(
        self, organizacion_client, reserva_por_pagar
    ):
        resp = organizacion_client.post(URL_INICIAR.format(reserva_por_pagar.pk))
        assert resp.status_code == 200
        assert Pago.objects.filter(reserva=reserva_por_pagar).count() == 1

    def test_anonimo_sin_token_recibe_401(self, anon_client, reserva_por_pagar):
        resp = anon_client.post(URL_INICIAR.format(reserva_por_pagar.pk))
        assert resp.status_code == 401

    def test_token_invalido_recibe_403(self, anon_client, reserva_por_pagar):
        resp = anon_client.post(
            f"{URL_INICIAR.format(reserva_por_pagar.pk)}?token=no-es-el-token"
        )
        assert resp.status_code == 403

    def test_usuario_ajeno_recibe_403(self, profesional_client, reserva_por_pagar):
        resp = profesional_client.post(URL_INICIAR.format(reserva_por_pagar.pk))
        assert resp.status_code == 403

    def test_admin_puede_iniciar(self, admin_client, reserva_por_pagar):
        resp = admin_client.post(URL_INICIAR.format(reserva_por_pagar.pk))
        assert resp.status_code == 200

    def test_reinicio_es_idempotente(self, anon_client, reserva_por_pagar):
        primero = _iniciar_por_token(anon_client, reserva_por_pagar)
        segundo = _iniciar_por_token(anon_client, reserva_por_pagar)

        assert segundo["token"] == primero["token"]
        assert segundo["referencia_publica"] == primero["referencia_publica"]
        assert Pago.objects.filter(reserva=reserva_por_pagar).count() == 1

    def test_el_monto_sale_del_servidor(self, anon_client, reserva_por_pagar):
        token = reserva_por_pagar.generar_token()
        resp = anon_client.post(
            f"{URL_INICIAR.format(reserva_por_pagar.pk)}?token={token}",
            {"monto": 1, "moneda": "USD"},
            format="json",
        )
        assert resp.status_code == 200
        pago = Pago.objects.get(referencia_publica=resp.data["referencia_publica"])
        assert pago.monto_total == int(reserva_por_pagar.precio_acordado)

    def test_reserva_ya_pagada_no_inicia_otro_pago(
        self, organizacion_client, reserva_pendiente
    ):
        resp = organizacion_client.post(URL_INICIAR.format(reserva_pendiente.pk))
        assert resp.status_code == 400


@pytest.mark.django_db
class TestRetornoPagoView:
    def test_retorno_exitoso_activa_la_reserva(self, anon_client, reserva_por_pagar):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        resp = anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})

        assert resp.status_code == 302
        consulta = parse_qs(urlsplit(resp["Location"]).query)
        assert consulta["estado"] == ["ok"]
        assert consulta["ref"] == [datos["referencia_publica"]]

        reserva_por_pagar.refresh_from_db()
        assert reserva_por_pagar.estado == Reserva.ESTADO_PENDIENTE_ACEPTACION
        pago = Pago.objects.get(referencia_publica=datos["referencia_publica"])
        assert pago.estado == estados.AUTORIZADO

    def test_retorno_por_post_tambien_confirma(self, anon_client, reserva_por_pagar):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        resp = anon_client.post(URL_RETORNO, {"token_ws": datos["token"]})

        assert resp.status_code == 302
        assert parse_qs(urlsplit(resp["Location"]).query)["estado"] == ["ok"]

    def test_retorno_duplicado_no_duplica_efectos(
        self, anon_client, reserva_por_pagar
    ):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        primera = anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})
        segunda = anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})

        assert primera.status_code == segunda.status_code == 302
        assert parse_qs(urlsplit(segunda["Location"]).query)["estado"] == ["ok"]
        pago = Pago.objects.get(referencia_publica=datos["referencia_publica"])
        assert pago.eventos.filter(a_estado=estados.AUTORIZADO).count() == 1

    def test_pago_rechazado_cancela_la_reserva(self, anon_client, reserva_por_pagar):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)
        FakeGateway.configurar(modo="rechazar")

        resp = anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})

        consulta = parse_qs(urlsplit(resp["Location"]).query)
        assert consulta["estado"] == ["fallo"]
        reserva_por_pagar.refresh_from_db()
        assert reserva_por_pagar.estado == Reserva.ESTADO_CANCELADA
        pago = Pago.objects.get(referencia_publica=datos["referencia_publica"])
        assert pago.estado == estados.RECHAZADO

    def test_abandono_marca_rechazado_y_usa_estado_abandono(
        self, anon_client, reserva_por_pagar
    ):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        resp = anon_client.get(URL_RETORNO, {"TBK_TOKEN": datos["token"]})

        consulta = parse_qs(urlsplit(resp["Location"]).query)
        assert consulta["estado"] == ["abandono"]
        assert consulta["ref"] == [datos["referencia_publica"]]
        reserva_por_pagar.refresh_from_db()
        assert reserva_por_pagar.estado == Reserva.ESTADO_CANCELADA

    def test_abandono_tras_pago_exitoso_reporta_ok(
        self, anon_client, reserva_por_pagar
    ):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)
        anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})

        resp = anon_client.get(URL_RETORNO, {"TBK_TOKEN": datos["token"]})

        assert parse_qs(urlsplit(resp["Location"]).query)["estado"] == ["ok"]

    def test_monto_alterado_deja_pago_en_revision_manual(
        self, anon_client, reserva_por_pagar
    ):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)
        FakeGateway.configurar(monto_alterado=1)

        resp = anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})

        assert parse_qs(urlsplit(resp["Location"]).query)["estado"] == ["fallo"]
        pago = Pago.objects.get(referencia_publica=datos["referencia_publica"])
        assert pago.estado == estados.REVISION_MANUAL
        reserva_por_pagar.refresh_from_db()
        assert reserva_por_pagar.estado == Reserva.ESTADO_PENDIENTE_PAGO

    def test_token_desconocido_redirige_a_fallo(self, anon_client):
        resp = anon_client.get(URL_RETORNO, {"token_ws": "NO-EXISTE"})

        consulta = parse_qs(urlsplit(resp["Location"]).query)
        assert consulta == {"estado": ["fallo"]}

    def test_retorno_sin_parametros_redirige_a_fallo(self, anon_client):
        resp = anon_client.get(URL_RETORNO)
        assert parse_qs(urlsplit(resp["Location"]).query) == {"estado": ["fallo"]}

    def test_la_url_de_retorno_no_expone_token_ni_monto(
        self, anon_client, reserva_por_pagar
    ):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        location = anon_client.get(
            URL_RETORNO, {"token_ws": datos["token"]}
        )["Location"]

        assert datos["token"] not in location
        assert "monto" not in location.lower()
        assert set(parse_qs(urlsplit(location).query)) == {"ref", "estado"}

    def test_post_exento_de_csrf(self, reserva_por_pagar):
        cliente = APIClient(enforce_csrf_checks=True)
        datos = _iniciar_por_token(cliente, reserva_por_pagar)

        resp = cliente.post(URL_RETORNO, {"token_ws": datos["token"]})

        assert resp.status_code == 302


@pytest.mark.django_db
class TestEstadoPagoView:
    def test_estado_inicial(self, anon_client, reserva_por_pagar):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)

        resp = anon_client.get(URL_ESTADO.format(datos["referencia_publica"]))

        assert resp.status_code == 200
        assert resp.data["estado"] == estados.INICIADO
        assert resp.data["reserva_estado"] == Reserva.ESTADO_PENDIENTE_PAGO
        assert "token" not in resp.data
        assert "monto_total" not in resp.data

    def test_estado_tras_pago(self, anon_client, reserva_por_pagar):
        datos = _iniciar_por_token(anon_client, reserva_por_pagar)
        anon_client.get(URL_RETORNO, {"token_ws": datos["token"]})

        resp = anon_client.get(URL_ESTADO.format(datos["referencia_publica"]))

        assert resp.data["estado"] == estados.AUTORIZADO
        assert resp.data["reserva_estado"] == Reserva.ESTADO_PENDIENTE_ACEPTACION

    def test_referencia_desconocida_da_404(self, anon_client):
        resp = anon_client.get(URL_ESTADO.format("00000000-0000-0000-0000-000000000000"))
        assert resp.status_code == 404
