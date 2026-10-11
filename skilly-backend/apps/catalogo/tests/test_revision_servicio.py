"""
Tests de RevisionServicio: bitácora de moderación de servicios (DoD 2.6).

Cada transición de moderación (aprobar, devolver, rechazar, suspender) debe
dejar un registro inmutable con el admin que la ejecutó y el comentario.
"""
import pytest

from apps.catalogo.models import RevisionServicio


@pytest.mark.django_db
class TestRevisionServicio:
    def test_aprobar_registra_revision(self, servicio_en_revision, usuario_admin):
        servicio_en_revision.aprobar(usuario_admin)

        revision = RevisionServicio.objects.get(servicio=servicio_en_revision)
        assert revision.accion == RevisionServicio.ACCION_APROBAR
        assert revision.admin == usuario_admin
        assert revision.comentario == ""

    def test_devolver_registra_revision_con_comentario(
        self, servicio_en_revision, usuario_admin
    ):
        servicio_en_revision.devolver(usuario_admin, "Falta describir entregables.")

        revision = RevisionServicio.objects.get(servicio=servicio_en_revision)
        assert revision.accion == RevisionServicio.ACCION_DEVOLVER
        assert revision.comentario == "Falta describir entregables."

    def test_rechazar_registra_revision_con_comentario(
        self, servicio_en_revision, usuario_admin
    ):
        servicio_en_revision.rechazar(usuario_admin, "No cumple las políticas.")

        revision = RevisionServicio.objects.get(servicio=servicio_en_revision)
        assert revision.accion == RevisionServicio.ACCION_RECHAZAR
        assert revision.comentario == "No cumple las políticas."

    def test_suspender_registra_revision(self, servicio_aprobado, usuario_admin):
        servicio_aprobado.suspender(usuario_admin)

        revision = RevisionServicio.objects.get(servicio=servicio_aprobado)
        assert revision.accion == RevisionServicio.ACCION_SUSPENDER

    def test_historial_acumula_varias_revisiones(self, servicio_en_revision, usuario_admin):
        servicio_en_revision.devolver(usuario_admin, "Ajustar precio.")
        servicio_en_revision.publicar()
        servicio_en_revision.aprobar(usuario_admin)

        acciones = list(
            RevisionServicio.objects.filter(servicio=servicio_en_revision).values_list(
                "accion", flat=True
            )
        )
        assert acciones == [
            RevisionServicio.ACCION_APROBAR,
            RevisionServicio.ACCION_DEVOLVER,
        ]
