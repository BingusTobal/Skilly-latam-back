"""
Pruebas del flujo JWT. Ticket 0.17.

Incluye el caso que solo se detecta probando de verdad: el refresh rotado
queda en blacklist y el token viejo no sirve. Ese caso fue el que destapo que
faltaba registrar rest_framework_simplejwt.token_blacklist en INSTALLED_APPS.
"""
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.auth

CREDENCIALES = {"email": "jwt@test.skilly", "password": "JwtTest123!"}


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user(
        email=CREDENCIALES["email"], password=CREDENCIALES["password"]
    )


@pytest.fixture
def client():
    return APIClient()


class TestObtenerToken:
    def test_login_con_email_devuelve_access_y_refresh(self, client, usuario):
        respuesta = client.post(reverse("token_obtain_pair"), CREDENCIALES, format="json")
        assert respuesta.status_code == 200
        assert "access" in respuesta.json()
        assert "refresh" in respuesta.json()

    def test_password_incorrecto_es_401(self, client, usuario):
        respuesta = client.post(
            reverse("token_obtain_pair"),
            {"email": CREDENCIALES["email"], "password": "incorrecta"},
            format="json",
        )
        assert respuesta.status_code == 401

    def test_email_inexistente_es_401(self, client, db):
        respuesta = client.post(
            reverse("token_obtain_pair"),
            {"email": "nadie@test.skilly", "password": "loquesea1"},
            format="json",
        )
        assert respuesta.status_code == 401

    def test_el_campo_requerido_es_email(self, client, usuario):
        """El serializer de simplejwt exige el campo `email` (USERNAME_FIELD)."""
        respuesta = client.post(
            reverse("token_obtain_pair"),
            {"username": CREDENCIALES["email"], "password": CREDENCIALES["password"]},
            format="json",
        )
        # 400 por campo faltante, no 200: el login no acepta username.
        assert respuesta.status_code == 400
        assert "email" in respuesta.json()


class TestRotacionYBlacklist:
    def test_refresh_rota_el_token(self, client, usuario):
        original = client.post(
            reverse("token_obtain_pair"), CREDENCIALES, format="json"
        ).json()["refresh"]

        respuesta = client.post(
            reverse("token_refresh"), {"refresh": original}, format="json"
        )
        assert respuesta.status_code == 200
        assert "access" in respuesta.json()
        assert "refresh" in respuesta.json(), "ROTATE_REFRESH_TOKENS debe devolver refresh"
        assert respuesta.json()["refresh"] != original

    def test_refresh_viejo_queda_blacklisted(self, client, usuario):
        """El token rotado no puede reutilizarse."""
        original = client.post(
            reverse("token_obtain_pair"), CREDENCIALES, format="json"
        ).json()["refresh"]

        client.post(reverse("token_refresh"), {"refresh": original}, format="json")

        # Segundo uso del token viejo: debe rechazarse.
        reutilizado = client.post(
            reverse("token_refresh"), {"refresh": original}, format="json"
        )
        assert reutilizado.status_code == 401, (
            "BLACKLIST_AFTER_ROTATION no esta funcionando: el refresh viejo "
            "sigue siendo valido."
        )

    def test_refresh_nuevo_si_sirve(self, client, usuario):
        original = client.post(
            reverse("token_obtain_pair"), CREDENCIALES, format="json"
        ).json()["refresh"]

        rotado = client.post(
            reverse("token_refresh"), {"refresh": original}, format="json"
        ).json()

        segundo = client.post(
            reverse("token_refresh"), {"refresh": rotado["refresh"]}, format="json"
        )
        assert segundo.status_code == 200

class TestAccesoConToken:
    """Permiso por defecto: los endpoints exigen autenticacion (0.17)."""

    def test_configuracion_por_defecto(self):
        assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == (
            "rest_framework.permissions.IsAuthenticated",
        )

    def test_sin_token_es_401(self, cliente_endpoint_protegido):
        assert cliente_endpoint_protegido.get("/protegido/").status_code == 401

    def test_access_token_autentica(self, cliente_endpoint_protegido, usuario, client):
        # El fixture sobrescribe ROOT_URLCONF con urls_test, que replica el
        # enrutado real de auth mas el endpoint protegido.
        tokens = client.post(
            "/api/auth/token/", CREDENCIALES, format="json"
        ).json()
        cliente_endpoint_protegido.credentials(
            HTTP_AUTHORIZATION=f"Bearer {tokens['access']}"
        )
        respuesta = cliente_endpoint_protegido.get("/protegido/")
        assert respuesta.status_code == 200
        assert respuesta.json()["ok"] is True

    def test_token_invalido_es_401(self, cliente_endpoint_protegido):
        cliente_endpoint_protegido.credentials(HTTP_AUTHORIZATION="Bearer token.invalido")
        assert cliente_endpoint_protegido.get("/protegido/").status_code == 401


@pytest.fixture
def cliente_endpoint_protegido(settings):
    """Cliente contra un urls de test con un endpoint protegido."""
    settings.ROOT_URLCONF = "apps.usuarios.tests.urls_test"
    return APIClient()
