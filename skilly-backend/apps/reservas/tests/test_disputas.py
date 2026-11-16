"""Disputas E2E (Sprint 5, tickets 5.1–5.3).

Cubre apertura por organización o profesional, evidencia sin depender de S3,
permisos de las partes y resolución del admin con efecto sobre el pago.
"""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.pagos import estados
from apps.pagos.models import Pago
from apps.reservas import services
from apps.reservas.models import Disputa, EvidenciaDisputa, Reserva

URL_DISPUTAS = "/api/disputas/"


@pytest.fixture(autouse=True)
def media_temporal(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def reserva_entregada(reserva_pendiente):
    services.aceptar(reserva_pendiente)
    services.marcar_entregado(reserva_pendiente)
    return reserva_pendiente


@pytest.fixture
def disputa_abierta(reserva_entregada, usuario_organizacion):
    return services.abrir_disputa(
        reserva_entregada,
        usuario_organizacion,
        "Entrega incompleta",
        "Faltó la mitad de los entregables.",
    )


def _pdf(nombre="evidencia.pdf"):
    return SimpleUploadedFile(
        nombre, b"%PDF-1.4 evidencia", content_type="application/pdf"
    )


def _abrir(client, reserva, motivo="Entrega incompleta", **extra):
    cuerpo = {"reserva": reserva.pk, "motivo": motivo}
    cuerpo.update(extra)
    return client.post(URL_DISPUTAS, cuerpo, format="multipart")


@pytest.mark.django_db
@pytest.mark.reservas
class TestAperturaDisputa:
    def test_organizacion_abre_disputa_con_evidencia(
        self, organizacion_client, reserva_entregada, organizacion
    ):
        resp = _abrir(
            organizacion_client,
            reserva_entregada,
            descripcion="Solo entregó el 50%.",
            evidencia=_pdf(),
        )

        assert resp.status_code == 201
        assert resp.data["estado"] == Disputa.ESTADO_ABIERTA
        assert resp.data["abierta_por"] == "Marcela Ibanez"
        assert len(resp.data["evidencias"]) == 1

        reserva_entregada.refresh_from_db()
        assert reserva_entregada.estado == Reserva.ESTADO_CON_DISPUTA
        assert EvidenciaDisputa.objects.filter(disputa_id=resp.data["id"]).count() == 1

        pago = Pago.objects.get(reserva=reserva_entregada)
        assert pago.estado == estados.RETENIDO

    def test_profesional_puede_abrir_disputa(
        self, profesional_client, reserva_entregada
    ):
        resp = _abrir(profesional_client, reserva_entregada, motivo="La organización no responde")

        assert resp.status_code == 201
        reserva_entregada.refresh_from_db()
        assert reserva_entregada.estado == Reserva.ESTADO_CON_DISPUTA

    def test_tercero_no_puede_abrir_disputa(
        self, reserva_entregada, profesional_otro
    ):
        cliente = APIClient()
        cliente.force_authenticate(user=profesional_otro.usuario)

        resp = _abrir(cliente, reserva_entregada)

        assert resp.status_code == 403

    def test_anonimo_no_puede_abrir_disputa(self, anon_client, reserva_entregada):
        resp = _abrir(anon_client, reserva_entregada)

        assert resp.status_code in (401, 403)

    def test_admin_tampoco_abre_disputas(self, admin_client, reserva_entregada):
        resp = _abrir(admin_client, reserva_entregada)

        assert resp.status_code == 403

    def test_no_se_abre_si_la_reserva_no_es_disputable(
        self, organizacion_client, reserva_pendiente
    ):
        resp = _abrir(organizacion_client, reserva_pendiente)

        assert resp.status_code == 400

    def test_no_se_abre_dos_veces(self, organizacion_client, disputa_abierta):
        resp = _abrir(organizacion_client, disputa_abierta.reserva)

        assert resp.status_code == 400

    def test_rechaza_archivo_no_permitido(
        self, organizacion_client, reserva_entregada
    ):
        archivo = SimpleUploadedFile(
            "notas.txt", b"texto", content_type="text/plain"
        )
        resp = _abrir(organizacion_client, reserva_entregada, evidencia=archivo)

        assert resp.status_code == 400

    def test_agrega_evidencia_despues_de_abrir(
        self, organizacion_client, disputa_abierta
    ):
        resp = organizacion_client.post(
            f"{URL_DISPUTAS}{disputa_abierta.pk}/evidencias/",
            {"archivo": _pdf("captura.png"), "nombre": "Captura"},
            format="multipart",
        )

        assert resp.status_code == 201
        assert resp.data["nombre"] == "Captura"
        assert EvidenciaDisputa.objects.filter(disputa=disputa_abierta).count() == 1

    def test_lista_solo_las_disputas_propias(
        self, organizacion_client, profesional_client, disputa_abierta
    ):
        resp_org = organizacion_client.get(URL_DISPUTAS)
        resp_pro = profesional_client.get(URL_DISPUTAS)

        assert resp_org.status_code == 200
        assert len(resp_org.data) == 1
        assert resp_pro.status_code == 200
        assert len(resp_pro.data) == 1


@pytest.mark.django_db
@pytest.mark.reservas
class TestResolucionDisputa:
    def _resolver(self, admin_client, disputa, **cuerpo):
        cuerpo.setdefault("resolucion", "Revisado por el equipo de Skilly.")
        return admin_client.post(
            f"/api/admin/disputas/{disputa.pk}/resolver/", cuerpo, format="json"
        )

    def test_a_favor_organizacion_reembolsa_todo(
        self, admin_client, disputa_abierta
    ):
        resp = self._resolver(
            admin_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_ORGANIZACION,
        )

        assert resp.status_code == 200
        assert resp.data["estado"] == Disputa.ESTADO_RESUELTA
        assert resp.data["resultado"] == Disputa.RESULTADO_ORGANIZACION

        pago = Pago.objects.get(reserva=disputa_abierta.reserva)
        assert pago.estado == estados.REEMBOLSADO
        assert pago.monto_reembolsado == pago.monto_total

        reserva = Reserva.objects.get(pk=disputa_abierta.reserva_id)
        assert reserva.estado == Reserva.ESTADO_FINALIZADA

    def test_a_favor_profesional_libera_el_pago(
        self, admin_client, disputa_abierta
    ):
        resp = self._resolver(
            admin_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_PROFESIONAL,
        )

        assert resp.status_code == 200
        pago = Pago.objects.get(reserva=disputa_abierta.reserva)
        assert pago.estado == estados.LIBERADO
        assert pago.liberado_en is not None

    def test_division_reembolsa_y_libera_el_saldo(
        self, admin_client, disputa_abierta
    ):
        resp = self._resolver(
            admin_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_DIVISION,
            porcentaje_reembolso=40,
        )

        assert resp.status_code == 200
        assert resp.data["porcentaje_reembolso"] == 40
        assert resp.data["monto_reembolso"] == Decimal("60000.00")

        pago = Pago.objects.get(reserva=disputa_abierta.reserva)
        assert pago.estado == estados.LIBERADO
        assert pago.monto_reembolsado == 60000

    def test_division_exige_porcentaje(self, admin_client, disputa_abierta):
        resp = self._resolver(
            admin_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_DIVISION,
        )

        assert resp.status_code == 400

    def test_solo_admin_resuelve(self, organizacion_client, disputa_abierta):
        resp = self._resolver(
            organizacion_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_PROFESIONAL,
        )

        assert resp.status_code == 403

    def test_no_se_resuelve_dos_veces(self, admin_client, disputa_abierta):
        self._resolver(
            admin_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_PROFESIONAL,
        )
        resp = self._resolver(
            admin_client,
            disputa_abierta,
            resultado=Disputa.RESULTADO_ORGANIZACION,
        )

        assert resp.status_code == 400

    def test_admin_ve_la_disputa_con_pago_y_evidencia(
        self, admin_client, disputa_abierta
    ):
        services.agregar_evidencia(disputa_abierta, _pdf(), nombre="Prueba")

        resp = admin_client.get("/api/admin/disputas/?estado=abierta")

        assert resp.status_code == 200
        assert len(resp.data) == 1
        caso = resp.data[0]
        assert caso["pago_estado"] == estados.RETENIDO
        assert caso["monto_retenido"] == 150000
        assert caso["organizacion"] == "Constructora Prueba Ltda."
        assert len(caso["evidencias"]) == 1
