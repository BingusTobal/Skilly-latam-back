"""
Tests de los endpoints del panel admin (Iteración 5, tickets 5.7 y 5.8).

Cubren las vistas que cruzan apps: resumen, comisiones, disputas, listados de
profesionales/organizaciones y la ficha de una organización. Lo importante es
que los reportes salgan de los pagos LIBERADOS (no de reservas sueltas) y que
las columnas derivadas de los listados no dependan de N+1 silenciosos.
"""
import pytest
from django.utils import timezone

from apps.pagos.models import Pago

pytestmark = pytest.mark.django_db


class TestAccesoAdmin:
    @pytest.mark.parametrize(
        "url",
        [
            "/api/admin/resumen/",
            "/api/admin/comisiones/",
            "/api/admin/disputas/",
            "/api/auth/admin/profesionales/",
            "/api/auth/admin/organizaciones/",
        ],
    )
    def test_sin_sesion_no_se_puede_entrar(self, anon_client, url):
        assert anon_client.get(url).status_code in (401, 403)

    def test_profesional_no_puede_entrar_al_resumen(self, profesional_client):
        assert profesional_client.get("/api/admin/resumen/").status_code == 403


class TestResumen:
    def test_devuelve_kpis_y_actividad(self, admin_client, postulacion, servicio_aprobado):
        datos = admin_client.get("/api/admin/resumen/").json()

        assert set(datos) == {"kpis", "servicios_por_categoria", "actividad"}
        assert datos["kpis"]["postulaciones_pendientes"] == 1
        assert datos["kpis"]["servicios_activos"] == 1
        assert datos["kpis"]["disputas_abiertas"] == 0
        assert datos["kpis"]["comision_mes"] == 0
        assert datos["kpis"]["reservas_activas"] == 0
        assert datos["kpis"]["ingresos_mes"] == 0
        assert datos["kpis"]["tasa_disputas"] == 0
        assert any(
            fila["categoria"] == servicio_aprobado.categoria.nombre
            for fila in datos["servicios_por_categoria"]
        )
        assert any(
            "postulación" in item["texto"].lower() for item in datos["actividad"]
        )


class TestComisiones:
    def test_calcula_la_comision_del_mes_del_pago_liberado(
        self, admin_client, reserva_pendiente
    ):
        pago = Pago.objects.get(reserva=reserva_pendiente)
        Pago.objects.filter(pk=pago.pk).update(
            estado="liberado", liberado_en=timezone.now()
        )

        datos = admin_client.get("/api/admin/comisiones/").json()

        assert datos["comision_mes"] == pago.monto_comision
        assert datos["servicios_facturados"] == 1
        assert datos["comision_promedio"] == pago.monto_comision
        assert datos["detalle"][0]["servicio"] == reserva_pendiente.servicio.titulo
        assert datos["por_categoria"][0]["monto"] == pago.monto_comision

    def test_un_pago_retenido_no_cuenta_como_comision(
        self, admin_client, reserva_pendiente
    ):
        datos = admin_client.get("/api/admin/comisiones/").json()
        assert datos["comision_mes"] == 0
        assert datos["detalle"] == []

    def test_mes_invalido_devuelve_400(self, admin_client):
        respuesta = admin_client.get("/api/admin/comisiones/?mes=2026-13")
        assert respuesta.status_code == 400

    def test_variacion_es_nula_si_el_mes_anterior_no_tiene_datos(
        self, admin_client, reserva_pendiente
    ):
        pago = Pago.objects.get(reserva=reserva_pendiente)
        Pago.objects.filter(pk=pago.pk).update(
            estado="liberado", liberado_en=timezone.now()
        )
        datos = admin_client.get("/api/admin/comisiones/").json()
        assert datos["comision_mes_anterior"] == 0
        assert datos["variacion_pct"] is None


class TestListadosAdmin:
    def test_organizaciones_agregan_reservas_y_gasto(
        self, admin_client, organizacion, reserva_por_pagar
    ):
        datos = admin_client.get("/api/auth/admin/organizaciones/").json()
        fila = next(o for o in datos if o["id"] == organizacion.id)

        assert fila["reservas_count"] == 1
        assert int(fila["gasto_total"]) == int(reserva_por_pagar.precio_acordado)
        assert fila["ultima_reserva"] is not None

    def test_profesionales_traen_especialidad_y_completados(
        self, admin_client, profesional, postulacion
    ):
        datos = admin_client.get("/api/auth/admin/profesionales/").json()
        fila = next(p for p in datos if p["id"] == profesional.id)

        assert fila["especialidad"] == postulacion.especialidad
        assert fila["servicios_completados"] == 0
        assert fila["disputas_abiertas"] == 0
        assert fila["postulaciones_pendientes"] == 1

    def test_ficha_de_organizacion_devuelve_su_historial(
        self, admin_client, organizacion, reserva_por_pagar
    ):
        datos = admin_client.get(
            f"/api/auth/admin/organizaciones/{organizacion.id}/"
        ).json()

        assert datos["organizacion"]["id"] == organizacion.id
        assert datos["kpis"]["reservas"] == 1
        assert int(datos["kpis"]["gasto_total"]) == int(
            reserva_por_pagar.precio_acordado
        )
        assert len(datos["reservas"]) == 1
