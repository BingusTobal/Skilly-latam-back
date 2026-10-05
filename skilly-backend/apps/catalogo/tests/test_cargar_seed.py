"""
Pruebas del comando cargar_seed. Ticket 0.15.

El seed tiene que ser idempotente: se ejecuta cada vez que se levanta el
entorno y nunca debe duplicar datos.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.catalogo.models import Categoria

Usuario = get_user_model()


class TestCategorias:
    def test_carga_las_5_categorias(self, db):
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        assert Categoria.objects.count() == 5

    def test_las_categorias_son_las_de_los_mockups(self, db):
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        nombres = set(Categoria.objects.values_list("nombre", flat=True))
        assert nombres == {
            "Salud y Bienestar",
            "Desarrollo software",
            "Diseño gráfico",
            "Marketing",
            "Finanzas",
        }

    def test_las_categorias_nacen_aprobadas(self, db):
        """Publicar un servicio exige categoria aprobada."""
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        assert Categoria.objects.filter(aprobada=False).count() == 0

    def test_es_idempotente(self, db):
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        assert Categoria.objects.count() == 5

    def test_slugs_unicos_y_legibles(self, db):
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        slugs = list(Categoria.objects.values_list("slug", flat=True))
        assert len(set(slugs)) == 5
        assert "diseno-grafico" in slugs


class TestAdministrador:
    def test_crea_administrador(self, db):
        call_command(
            "cargar_seed",
            "--admin-email",
            "root@skilly.cl",
            "--admin-password",
            "ClaveSegura123!",
            verbosity=0,
        )
        admin = Usuario.objects.get(email="root@skilly.cl")
        assert admin.is_admin is True
        assert admin.is_superuser is True
        assert admin.tipo == Usuario.TIPO_ADMIN
        assert admin.check_password("ClaveSegura123!")

    def test_no_duplica_administrador(self, db):
        argumentos = ["--admin-email", "root@skilly.cl", "--admin-password", "ClaveSegura123!"]
        call_command("cargar_seed", *argumentos, verbosity=0)
        call_command("cargar_seed", *argumentos, verbosity=0)
        assert Usuario.objects.filter(email="root@skilly.cl").count() == 1

    def test_password_se_hashea(self, db):
        call_command(
            "cargar_seed",
            "--admin-email",
            "root@skilly.cl",
            "--admin-password",
            "ClaveSegura123!",
            verbosity=0,
        )
        admin = Usuario.objects.get(email="root@skilly.cl")
        assert admin.password != "ClaveSegura123!"

    def test_email_se_normaliza_a_minusculas(self, db):
        call_command(
            "cargar_seed",
            "--admin-email",
            "  ROOT@Skilly.CL  ",
            "--admin-password",
            "ClaveSegura123!",
            verbosity=0,
        )
        assert Usuario.objects.filter(email="root@skilly.cl").exists()

    def test_sin_admin_no_crea_usuarios(self, db):
        call_command("cargar_seed", "--sin-admin", verbosity=0)
        assert Usuario.objects.count() == 0

    def test_advertencia_de_password_por_defecto(self, db, capsys):
        call_command("cargar_seed", verbosity=0)
        salida = capsys.readouterr().out
        assert "password por defecto" in salida