"""Configuración versionada de la tasa de comisión (Iteración 5, ticket 5.4).

RF-30: se configura la tasa. R17: cambiarla no altera pagos ya liberados ni
reservas ya creadas, porque ambos guardan un snapshot.
"""
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.comisiones.models import TasaComision
from apps.comisiones.services import tasa_efectiva
from apps.pagos.models import Pago
from apps.reservas.services import crear_reserva

URL = "/api/admin/tasas-comision/"

pytestmark = pytest.mark.django_db


class TestCrudTasas:
    def test_admin_crea_tasa_global(self, admin_client, usuario_admin):
        resp = admin_client.post(URL, {"tasa": "0.1200"}, format="json")

        assert resp.status_code == 201
        assert resp.data["tasa"] == "0.1200"
        assert resp.data["categoria"] is None
        assert resp.data["creada_por"] == usuario_admin.pk
        assert TasaComision.objects.count() == 1

    def test_anonimo_no_puede_configurar(self, anon_client):
        assert anon_client.get(URL).status_code in (401, 403)
        assert anon_client.post(URL, {"tasa": "0.2"}).status_code in (401, 403)

    def test_profesional_no_puede_configurar(self, profesional_client):
        assert profesional_client.get(URL).status_code == 403

    def test_tasa_fuera_de_rango_devuelve_400(self, admin_client):
        assert admin_client.post(URL, {"tasa": "1.5"}, format="json").status_code == 400
        assert admin_client.post(URL, {"tasa": "-0.1"}, format="json").status_code == 400

    def test_no_permite_dos_versiones_globales_el_mismo_dia(self, admin_client):
        assert admin_client.post(URL, {"tasa": "0.10"}, format="json").status_code == 201
        resp = admin_client.post(URL, {"tasa": "0.12"}, format="json")

        assert resp.status_code == 400
        assert "vigente_desde" in resp.data

    def test_no_se_edita_el_valor_de_una_version(self, admin_client):
        creada = admin_client.post(URL, {"tasa": "0.10"}, format="json")

        resp = admin_client.patch(
            f"{URL}{creada.data['id']}/", {"tasa": "0.12"}, format="json"
        )

        assert resp.status_code == 400

    def test_se_puede_desactivar_sin_borrar_historial(self, admin_client):
        creada = admin_client.post(URL, {"tasa": "0.10"}, format="json")

        resp = admin_client.patch(
            f"{URL}{creada.data['id']}/", {"activa": False}, format="json"
        )

        assert resp.status_code == 200
        assert TasaComision.objects.get(pk=creada.data["id"]).activa is False

    def test_solo_se_eliminan_versiones_futuras(self, admin_client):
        hoy = admin_client.post(URL, {"tasa": "0.10"}, format="json")
        futura = admin_client.post(
            URL,
            {"tasa": "0.12", "vigente_desde": (timezone.localdate() + timedelta(days=10)).isoformat()},
            format="json",
        )

        assert admin_client.delete(f"{URL}{hoy.data['id']}/").status_code == 400
        assert admin_client.delete(f"{URL}{futura.data['id']}/").status_code == 204


class TestResolucionTasa:
    def test_categoria_tiene_prioridad_sobre_global(self, categoria, categoria_otra):
        TasaComision.objects.create(tasa=Decimal("0.10"), vigente_desde=date(2020, 1, 1))
        TasaComision.objects.create(
            categoria=categoria, tasa=Decimal("0.07"), vigente_desde=date(2020, 1, 1)
        )

        assert tasa_efectiva(categoria) == Decimal("0.0700")
        assert tasa_efectiva(categoria_otra) == Decimal("0.1000")

    def test_sin_tasas_usa_la_constante_de_settings(self, categoria):
        assert tasa_efectiva(categoria) == Decimal("0.1000")

    def test_version_futura_no_aplica_antes_de_su_fecha(self, categoria):
        TasaComision.objects.create(
            tasa=Decimal("0.10"), vigente_desde=date(2020, 1, 1)
        )
        TasaComision.objects.create(
            tasa=Decimal("0.20"),
            vigente_desde=timezone.localdate() + timedelta(days=5),
        )

        assert tasa_efectiva(categoria) == Decimal("0.1000")


class TestSnapshot:
    def test_nueva_tasa_no_altera_un_pago_ya_liberado(
        self, admin_client, reserva_pendiente
    ):
        pago = Pago.objects.get(reserva=reserva_pendiente)
        Pago.objects.filter(pk=pago.pk).update(
            estado="liberado", liberado_en=timezone.now()
        )
        pago.refresh_from_db()
        comision_original = pago.monto_comision

        admin_client.post(URL, {"tasa": "0.5000"}, format="json")

        pago.refresh_from_db()
        assert pago.monto_comision == comision_original
        assert pago.tasa_aplicada == Decimal("0.100")

    def test_reserva_nueva_toma_la_tasa_vigente(
        self,
        admin_client,
        categoria,
        servicio_aprobado,
        organizacion,
        horario_semanal,
        fecha_futura,
    ):
        admin_client.post(URL, {"tasa": "0.1500"}, format="json")

        reserva, _ = crear_reserva(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora_inicio=time(10, 0),
            datos={
                "nombre": "Marcela Ibáñez",
                "email": "organizacion@test.skilly",
                "telefono": "+56912345678",
            },
            organizacion=organizacion,
        )

        assert reserva.tasa_comision == Decimal("0.1500")


class TestCotizarNeto:
    def test_calculadora_publica_usa_la_tasa_vigente(self, anon_client, categoria):
        TasaComision.objects.create(
            categoria=categoria, tasa=Decimal("0.1500"), vigente_desde=date(2020, 1, 1)
        )

        resp = anon_client.get(
            "/api/tasa-neto/", {"precio": 100000, "categoria": categoria.id}
        )

        assert resp.status_code == 200
        assert resp.data == {"monto_neto": 85000}

    def test_precio_invalido_devuelve_400(self, anon_client):
        assert anon_client.get("/api/tasa-neto/", {"precio": "abc"}).status_code == 400
        assert anon_client.get("/api/tasa-neto/", {"precio": -1}).status_code == 400
