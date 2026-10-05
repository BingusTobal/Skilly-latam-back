"""
Pruebas del validador de RUT y del usuario custom. Tickets 0.11 y 0.13.

Los RUT de los mockups son invalidos (CONTEXTO-ARQUITECTURA.docx seccion 9.5).
Estas pruebas fijan ese comportamiento para que no se repita el error en el seed.
"""
import pytest
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.usuarios.models import Usuario, validar_rut


class TestValidarRut:
    @pytest.mark.parametrize(
        "rut",
        [
            "12.345.678-2",
            "12345678-2",
            "61.000.000-7",
            "1.234.567-8",
            "99999999-0",
        ],
    )
    def test_ruts_validos_pasan(self, rut):
        validar_rut(rut)

    @pytest.mark.parametrize(
        "rut",
        [
            # Los 5 RUT de los mockups, todos invalidos.
            "76.541.230-K",
            "77.902.114-5",
            "78.115.887-2",
            "76.220.556-9",
            "77.334.902-1",
            # Otros casos invalidos.
            "12.345.678-3",  # verificador incorrecto
            "12.345.678-5",  # verificador de un RUT inventado en tests previos
            "61.000.000-K",  # verificador incorrecto
            "01.234.567-8",  # no puede empezar en 0
            "abc-def",
            "1",
        ],
    )
    def test_ruts_invalidos_fallan(self, rut):
        with pytest.raises(ValueError):
            validar_rut(rut)

    def test_rut_acepta_puntos_y_guiones(self):
        validar_rut("12.345.678-2")
        validar_rut("123456782")
        with pytest.raises(ValueError):
            validar_rut("12.345.678-3")


class TestUsuarioCustom:
    def test_email_es_el_identificador(self, usuario_profesional):
        assert Usuario.USERNAME_FIELD == "email"
        assert usuario_profesional.USERNAME_FIELD == "email"
        assert usuario_profesional.username is None or usuario_profesional.username == ""

    def test_email_es_unico(self, usuario_profesional):
        with pytest.raises(Exception):
            get_user_model().objects.create_user(
                email="profesional@test.skilly",
                password="Otra123!",
            )

    def test_password_no_se_guarda_en_claro(self, usuario_profesional):
        assert usuario_profesional.password != "ProfTest123!"
        assert usuario_profesional.check_password("ProfTest123!")
        assert not usuario_profesional.check_password("incorrecta")

    def test_email_se_normaliza(self, usuario_profesional):
        assert usuario_profesional.email == usuario_profesional.email.lower().strip()

    def test_superusuario_requiere_staff(self):
        with pytest.raises(ValueError):
            get_user_model().objects.create_superuser(
                email="otro@test.skilly",
                password="X123!",
                is_staff=False,
            )

    def test_es_admin_plataforma(self, usuario_admin, usuario_profesional):
        assert usuario_admin.es_admin_plataforma is True
        assert usuario_profesional.es_admin_plataforma is False

    def test_nombre_completo(self, usuario_profesional):
        assert usuario_profesional.nombre_completo == "Juan Perez"


class TestTokenMagico:
    """Base para el Sprint 3, ticket 3.5."""

    def test_guarda_solo_el_hash(self, usuario_organizacion):
        token = usuario_organizacion.generar_token_magico()
        usuario_organizacion.refresh_from_db()

        assert token not in usuario_organizacion.token_magico_hash
        assert len(usuario_organizacion.token_magico_hash) == 64  # sha256 hex

    def test_token_valido(self, usuario_organizacion):
        token = usuario_organizacion.generar_token_magico()
        assert usuario_organizacion.token_magico_valido(token) is True

    def test_token_incorrecto_es_invalido(self, usuario_organizacion):
        usuario_organizacion.generar_token_magico()
        assert usuario_organizacion.token_magico_valido("token-falso") is False

    def test_token_un_solo_uso(self, usuario_organizacion):
        token = usuario_organizacion.generar_token_magico()
        usuario_organizacion.invalidar_token_magico()
        assert usuario_organizacion.token_magico_valido(token) is False

    def test_token_expirado_es_invalido(self, usuario_organizacion):
        from django.utils import timezone

        token = usuario_organizacion.generar_token_magico(horas_validez=1)
        usuario_organizacion.token_magico_expira = timezone.now() - timezone.timedelta(
            minutes=1
        )
        usuario_organizacion.save()
        assert usuario_organizacion.token_magico_valido(token) is False

    def test_dos_tokens_son_distintos(self, usuario_organizacion):
        primero = usuario_organizacion.generar_token_magico()
        segundo = usuario_organizacion.generar_token_magico()
        assert primero != segundo
        assert usuario_organizacion.token_magico_valido(segundo) is True
        assert usuario_organizacion.token_magico_valido(primero) is False