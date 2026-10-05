"""
Tests de los permisos globales. Tickets 0.8 y Sprint 1.

Estos permisos son la frontera de seguridad de toda la API, así que se prueban
como unidad: quién puede ver qué, y qué pasa cuando alguien no tiene permiso.

Un detalle que suele olvidarse: en DRF, `[PermisoA, PermisoB]` significa
"Y", no "O". Por eso existe `EsPostulanteOAdmin`, que implementa el "o" a mano
con `operadores.or_`. Hay un test que lo fija.
"""
import pytest
from rest_framework.test import APIRequestFactory

from apps.postulaciones.models import Postulacion
from apps.usuarios.permisos import (
    EsAdmin,
    EsOrganizacion,
    EsPostulante,
    EsPostulanteOAdmin,
    EsProfesional,
    exception_handler,
)
from apps.usuarios.models import Organizacion, Profesional


def peticion(usuario):
    """Request con el usuario ya resuelto, como llega a la vista real."""
    request = APIRequestFactory().get("/api/qualquer-cosa/")
    request.user = usuario
    return request


@pytest.fixture
def profe_sin_postulacion(db, django_user_model):
    usuario = django_user_model.objects.create_user(
        email="profe.solo@test.skilly",
        password="ProfTest123!",
        tipo=django_user_model.TIPO_PROFESIONAL,
    )
    return usuario


# ===========================================================================
# EsOrganizacion / EsProfesional
# ===========================================================================
@pytest.mark.django_db
class TestRoles:
    def test_es_organizacion_acepta_a_una_organizacion(self, usuario_organizacion):
        assert EsOrganizacion().has_permission(peticion(usuario_organizacion), None)

    def test_es_organizacion_rechaza_a_un_profesional(self, usuario_profesional):
        assert not EsOrganizacion().has_permission(peticion(usuario_profesional), None)

    def test_es_organizacion_rechaza_a_un_admin(self, usuario_admin):
        """El admin es su propia cosa: `es_organizacion` es False aunque tenga
        todos los permisos. Por eso el panel usa `EsAdmin` y no `EsOrganizacion`."""
        assert not EsOrganizacion().has_permission(peticion(usuario_admin), None)

    def test_es_profesional_acepta_a_un_profesional(self, usuario_profesional):
        assert EsProfesional().has_permission(peticion(usuario_profesional), None)

    def test_es_profesional_rechaza_a_una_organizacion(self, usuario_organizacion):
        assert not EsProfesional().has_permission(peticion(usuario_organizacion), None)

    def test_anonimo_no_pasa(self):
        from django.contrib.auth.models import AnonymousUser

        assert not EsOrganizacion().has_permission(peticion(AnonymousUser()), None)
        assert not EsProfesional().has_permission(peticion(AnonymousUser()), None)
        assert not EsAdmin().has_permission(peticion(AnonymousUser()), None)


# ===========================================================================
# EsPostulante / EsPostulanteOAdmin
# ===========================================================================
@pytest.mark.django_db
class TestPostulante:
    def test_acepta_a_un_profesional(self, usuario_profesional):
        assert EsPostulante().has_permission(peticion(usuario_profesional), None)

    def test_rechaza_a_una_organizacion(self, usuario_organizacion):
        assert not EsPostulante().has_permission(peticion(usuario_organizacion), None)

    def test_una_cuenta_sin_ficha_pasa_pero_la_vista_responde_404(
        self, profe_sin_postulacion, anon_client
    ):
        """Una cuenta marcada como profesional sin ficha todavía pasa el
        permiso: el permiso solo mira el ROL. Lo que falta es la ficha, y eso lo
        responde la vista con un 404 ("todavía no te has postulado"), no un 403.
        Un 403 diría "prohibido" cuando en realidad no hay nada que ver."""
        assert EsPostulante().has_permission(peticion(profe_sin_postulacion), None)

        anon_client.force_authenticate(user=profe_sin_postulacion)
        assert anon_client.get("/api/postulaciones/mias/").status_code == 404

    def test_rechaza_a_un_admin(self, usuario_admin):
        """`EsPostulante` es solo el rol profesional. El admin entra por
        `EsAdmin`, y los dos se combinan en `EsPostulanteOAdmin`."""
        assert not EsPostulante().has_permission(peticion(usuario_admin), None)

    def test_el_o_de_postulante_o_admin(self, usuario_profesional, usuario_admin):
        """`[EsPostulante, EsAdmin]` en DRF significa "y": ningún usuario real
        pasa las dos. Por eso esta clase existe."""
        p = peticion(usuario_profesional)
        or_admin = EsPostulanteOAdmin()
        assert or_admin.has_permission(p, None)

        p = peticion(usuario_admin)
        assert or_admin.has_permission(p, None)

    def test_el_o_rechaza_a_una_organizacion(self, usuario_organizacion):
        assert not EsPostulanteOAdmin().has_permission(
            peticion(usuario_organizacion), None
        )


# ===========================================================================
# EsAdmin
# ===========================================================================
@pytest.mark.django_db
class TestAdmin:
    def test_acepta_a_un_superusuario(self, usuario_admin):
        assert EsAdmin().has_permission(peticion(usuario_admin), None)

    def test_rechaza_a_un_profesional(self, usuario_profesional):
        assert not EsAdmin().has_permission(peticion(usuario_profesional), None)

    def test_rechaza_a_una_organizacion(self, usuario_organizacion):
        assert not EsAdmin().has_permission(peticion(usuario_organizacion), None)

    def test_un_usuario_con_is_admin_sin_es_superusuario_pasa(self, django_user_model):
        """`is_admin` es el flag de plataforma del Sprint 0; `is_staff` es el de
        Django. Se usan los dos por separado a propósito."""
        usuario = django_user_model.objects.create_user(
            email="staff@test.skilly",
            password="StaffTest123!",
            is_admin=True,
            is_staff=False,
        )
        assert EsAdmin().has_permission(peticion(usuario), None)


# ===========================================================================
# exception_handler
# ===========================================================================
@pytest.mark.django_db
class TestExceptionHandler:
    def test_un_404_django_se_normaliza(self):
        from django.http import Http404

        respuesta = exception_handler(Http404("No existe"), {})
        assert respuesta.status_code == 404
        assert "detail" in respuesta.data

    def test_un_403_se_normaliza(self):
        from rest_framework.exceptions import PermissionDenied

        respuesta = exception_handler(PermissionDenied("No puede"), {})
        assert respuesta.status_code == 403
        assert "detail" in respuesta.data

    def test_todos_los_errores_usan_la_misma_clave(self, django_user_model):
        """Django y DRF deben responder con la misma forma, o el frontend
        tiene que probar dos claves segun de donde venga el fallo."""
        from django.core.exceptions import ValidationError
        from django.http import Http404
        from rest_framework.exceptions import NotFound, PermissionDenied

        for exc in (
            NotFound("x"),
            Http404("x"),
            ValidationError("x"),
            PermissionDenied("x"),
        ):
            assert set(exception_handler(exc, {}).data) == {"detail"}

    def test_una_excepcion_desconocida_devuelve_none(self):
        """Un error de programación no se disimula como respuesta JSON: el
        handler devuelve None y DRF lo vuelve a lanzar, para que reviente en
        los logs en vez de devolver un 200 vacío."""
        assert exception_handler(ValueError("bug"), {}) is None

    def test_una_validation_error_de_django_se_traduce(self):
        """Los `clean()` de los modelos usan `django.core.exceptions`, y DRF no
        los traduce solo: sin esto, devolver o rechazar una postulación sin
        comentarios darian 500 en vez de un 400 con el campo que falla."""
        from django.core.exceptions import ValidationError

        respuesta = exception_handler(
            ValidationError({"comentarios_admin": "Obligatorio."}), {}
        )
        assert respuesta.status_code == 400
        assert "comentarios_admin" in respuesta.data["detail"]