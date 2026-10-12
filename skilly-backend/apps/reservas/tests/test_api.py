"""
Tests de la API de reservas: creación con y sin cuenta, permisos por rol,
token mágico y visibilidad del monto neto (tickets 3.3 a 3.6).
"""
import pytest
from rest_framework.test import APIClient

from apps.reservas.models import Reserva

URL_RESERVAS = "/api/reservas/"


def _cuerpo(servicio, fecha, hora="10:00", email="invitado@test.skilly", **extra):
    cuerpo = {
        "servicio": servicio.id,
        "fecha": fecha.isoformat(),
        "hora_inicio": hora,
        "nombre": "Contacto Invitado",
        "email": email,
    }
    cuerpo.update(extra)
    return cuerpo


@pytest.mark.django_db
class TestCrearReservaAPI:
    def test_invitado_reserva_sin_cuenta(
        self, anon_client, servicio_aprobado, horario_semanal, fecha_futura
    ):
        resp = anon_client.post(
            URL_RESERVAS, _cuerpo(servicio_aprobado, fecha_futura), format="json"
        )
        assert resp.status_code == 201
        assert resp.data["token"]
        assert resp.data["estado"] == Reserva.ESTADO_PENDIENTE_ACEPTACION
        reserva = Reserva.objects.get(pk=resp.data["id"])
        assert reserva.organizacion.usuario is not None
        assert reserva.organizacion.modo == "invitada"

    def test_slot_ocupado_devuelve_400(
        self, anon_client, servicio_aprobado, horario_semanal, fecha_futura
    ):
        anon_client.post(
            URL_RESERVAS, _cuerpo(servicio_aprobado, fecha_futura), format="json"
        )
        resp = anon_client.post(
            URL_RESERVAS,
            _cuerpo(servicio_aprobado, fecha_futura, hora="10:30", email="otro@test.skilly"),
            format="json",
        )
        assert resp.status_code == 400

    def test_slots_es_publico(self, anon_client, servicio_aprobado, horario_semanal, fecha_futura):
        resp = anon_client.get(
            f"/api/servicios/{servicio_aprobado.id}/slots/?fecha={fecha_futura.isoformat()}"
        )
        assert resp.status_code == 200
        assert len(resp.data["slots"]) == 18

    def test_acceso_por_token(self, anon_client, servicio_aprobado, horario_semanal, fecha_futura):
        creada = anon_client.post(
            URL_RESERVAS, _cuerpo(servicio_aprobado, fecha_futura), format="json"
        ).data
        resp = anon_client.get(
            f"{URL_RESERVAS}{creada['id']}/?token={creada['token']}"
        )
        assert resp.status_code == 200
        assert resp.data["id"] == creada["id"]

    def test_token_invalido_da_404(self, anon_client, reserva_pendiente):
        resp = anon_client.get(f"{URL_RESERVAS}{reserva_pendiente.id}/?token=nope")
        assert resp.status_code == 404

    def test_rut_invalido_devuelve_400(
        self, anon_client, servicio_aprobado, horario_semanal, fecha_futura
    ):
        resp = anon_client.post(
            URL_RESERVAS,
            _cuerpo(servicio_aprobado, fecha_futura, rut="12.345.678-3"),
            format="json",
        )
        assert resp.status_code == 400
        assert "rut" in resp.data

    def test_profesional_autenticado_no_puede_reservar(
        self, profesional_client, servicio_aprobado, horario_semanal, fecha_futura
    ):
        resp = profesional_client.post(
            URL_RESERVAS, _cuerpo(servicio_aprobado, fecha_futura), format="json"
        )
        assert resp.status_code == 400
        assert Reserva.objects.count() == 0


@pytest.mark.django_db
class TestPermisos:
    def test_organizacion_no_ve_solicitudes(self, organizacion_client):
        resp = organizacion_client.get(f"{URL_RESERVAS}solicitudes/")
        assert resp.status_code == 403

    def test_profesional_no_ve_mias(self, profesional_client):
        resp = profesional_client.get(f"{URL_RESERVAS}mias/")
        assert resp.status_code == 403

    def test_profesional_ajeno_no_acepta(
        self, reserva_pendiente, profesional_otro
    ):
        client = APIClient()
        client.force_authenticate(user=profesional_otro.usuario)
        resp = client.post(f"{URL_RESERVAS}{reserva_pendiente.id}/aceptar/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestFlujoAPI:
    def test_flujo_completo_por_api(
        self, reserva_pendiente, profesional_client, organizacion_client
    ):
        resp = profesional_client.post(f"{URL_RESERVAS}{reserva_pendiente.id}/aceptar/")
        assert resp.status_code == 200
        assert resp.data["estado"] == Reserva.ESTADO_EN_CURSO

        resp = profesional_client.post(
            f"{URL_RESERVAS}{reserva_pendiente.id}/marcar-entregado/"
        )
        assert resp.data["estado"] == Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR

        resp = organizacion_client.post(
            f"{URL_RESERVAS}{reserva_pendiente.id}/confirmar-entrega/"
        )
        assert resp.data["estado"] == Reserva.ESTADO_FINALIZADA

    def test_profesional_ve_solo_monto_neto(self, reserva_pendiente, profesional_client):
        resp = profesional_client.get(f"{URL_RESERVAS}solicitudes/")
        assert resp.status_code == 200
        fila = resp.data["results"][0]
        assert "precio_acordado" not in fila
        assert fila["monto_neto"] == "135000.00"


@pytest.mark.django_db
class TestContactoProfesional:
    """La organización solo ve el contacto directo tras la aceptación."""

    def test_no_expone_contacto_antes_de_aceptar(
        self, reserva_pendiente, organizacion_client
    ):
        resp = organizacion_client.get(f"{URL_RESERVAS}{reserva_pendiente.id}/")
        assert resp.status_code == 200
        assert resp.data["profesional_email"] is None
        assert resp.data["profesional_telefono"] is None

    def test_expone_contacto_al_aceptar(
        self, reserva_pendiente, organizacion_client, profesional_client
    ):
        profesional_client.post(f"{URL_RESERVAS}{reserva_pendiente.id}/aceptar/")
        resp = organizacion_client.get(f"{URL_RESERVAS}{reserva_pendiente.id}/")
        assert (
            resp.data["profesional_email"]
            == reserva_pendiente.profesional.usuario.email
        )
        assert (
            resp.data["profesional_telefono"]
            == reserva_pendiente.profesional.telefono
        )
