"""
Fixtures compartidas de pytest. Ticket 0.16.

La configuracion de base de datos vive en config/settings_test.py (referenciado
desde pytest.ini). Aqui solo van las fixtures.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.usuarios.permisos import UsuarioTipo


@pytest.fixture
def usuario_admin(db):
    Usuario = get_user_model()
    return Usuario.objects.create_superuser(
        email="admin@test.skilly",
        password="AdminTest123!",
        first_name="Admin",
        last_name="Prueba",
        tipo=Usuario.TIPO_ADMIN,
        is_admin=True,
    )


@pytest.fixture
def usuario_profesional(db):
    Usuario = get_user_model()
    return Usuario.objects.create_user(
        email="profesional@test.skilly",
        password="ProfTest123!",
        first_name="Juan",
        last_name="Perez",
        tipo=Usuario.TIPO_PROFESIONAL,
    )


@pytest.fixture
def usuario_organizacion(db):
    Usuario = get_user_model()
    return Usuario.objects.create_user(
        email="organizacion@test.skilly",
        password="OrgTest123!",
        first_name="Marcela",
        last_name="Ibanez",
        tipo=Usuario.TIPO_ORGANIZACION,
    )


@pytest.fixture
def admin_client(usuario_admin):
    client = APIClient()
    client.force_authenticate(user=usuario_admin)
    return client


@pytest.fixture
def profesional_client(usuario_profesional):
    client = APIClient()
    client.force_authenticate(user=usuario_profesional)
    return client


@pytest.fixture
def organizacion_client(usuario_organizacion):
    client = APIClient()
    client.force_authenticate(user=usuario_organizacion)
    return client


@pytest.fixture
def anon_client():
    return APIClient()


@pytest.fixture
def tipo_organizacion():
    return UsuarioTipo.ORGANIZACION


@pytest.fixture
def tipo_profesional():
    return UsuarioTipo.PROFESIONAL
