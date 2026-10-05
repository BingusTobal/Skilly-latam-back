"""
Pruebas de los permisos RBAC. Ticket 0.13.

DoD punto 5: test del caso feliz + un caso de 403 por modulo.
"""
import pytest
from django.contrib.auth import get_user_model

from apps.usuarios.permisos import EsAdmin, EsOrganizacion, EsProfesional

pytestmark = pytest.mark.auth


class TestEsAdmin:
    def test_admin_plataforma_pasa(self, usuario_admin):
        class Vista:
            pass

        assert EsAdmin().has_permission(
            _request(usuario_admin), Vista()
        ) is True

    def test_usuario_normal_es_403(self, usuario_profesional):
        class Vista:
            pass

        assert EsAdmin().has_permission(
            _request(usuario_profesional), Vista()
        ) is False

    def test_anonimo_es_403(self, anon_client):
        class Vista:
            pass

        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get("/admin/whatever/")
        request.user = get_user_model().objects.none  # usuario no autenticado

        class Anon:
            is_authenticated = False
            is_admin = False
            es_admin_plataforma = False

        request.user = Anon()
        assert EsAdmin().has_permission(request, Vista()) is False


class TestEsOrganizacion:
    def test_organizacion_pasa(self, usuario_organizacion):
        assert EsOrganizacion().has_permission(
            _request(usuario_organizacion), object()
        ) is True

    def test_profesional_es_403(self, usuario_profesional):
        assert EsOrganizacion().has_permission(
            _request(usuario_profesional), object()
        ) is False


class TestEsProfesional:
    def test_profesional_pasa(self, usuario_profesional):
        assert EsProfesional().has_permission(
            _request(usuario_profesional), object()
        ) is True

    def test_organizacion_es_403(self, usuario_organizacion):
        assert EsProfesional().has_permission(
            _request(usuario_organizacion), object()
        ) is False


def _request(usuario):
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().get("/")
    request.user = usuario
    return request