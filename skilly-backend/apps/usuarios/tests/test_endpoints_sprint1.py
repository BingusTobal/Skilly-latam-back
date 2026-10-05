"""
Tests de API del Sprint 1: registro, login, perfil, password reset, horarios
y la cola de administración.

Cada test usa el cliente HTTP real (`APIClient`), no llamadas a las vistas: lo
que importa acá es el contrato que va a consumir el frontend, incluidos los
códigos de respuesta y las rutas de la respuesta de error.
"""
import pytest
from django.core import mail
from django.urls import reverse

from apps.postulaciones.models import Certificado, Postulacion
from apps.usuarios.models import Horario, Organizacion, Profesional

RUT_ORG_NUEVO = "18765321-5"
RUT_PROF_NUEVO = "24918073-K"


# ===========================================================================
# Registro de organización (1.6)
# ===========================================================================
@pytest.mark.django_db
class TestRegistroOrganizacion:
    url = "/api/auth/registro-organizacion/"

    def payload(self, **over):
        datos = {
            "nombre": "Constructora Nueva SpA",
            "giro": "Construcción",
            "nombre_contacto": "Marcela Ibáñez",
            "email_contacto": "nueva@test.skilly",
            "telefono": "+56912345678",
            "rut": RUT_ORG_NUEVO,
            "password": "OrgTest123!",
            "password_confirmacion": "OrgTest123!",
        }
        datos.update(over)
        return datos

    def test_registro_exitoso_devuelve_201(self, anon_client):
        respuesta = anon_client.post(self.url, self.payload(), format="json")
        assert respuesta.status_code == 201
        assert respuesta.data["nombre"] == "Constructora Nueva SpA"

    def test_crea_usuario_y_organizacion(self, anon_client):
        from django.contrib.auth import get_user_model

        Usuario = get_user_model()
        anon_client.post(self.url, self.payload(), format="json")

        usuario = Usuario.objects.get(email="nueva@test.skilly")
        assert usuario.tipo == Usuario.TIPO_ORGANIZACION
        assert Organizacion.objects.filter(usuario=usuario).exists()

    def test_no_devuelve_tokens(self, anon_client):
        """Decisión de diseño: el registro no autentica. Hay que hacer login
        después, así todo acceso queda registrado en el login."""
        respuesta = anon_client.post(self.url, self.payload(), format="json")
        assert "access" not in respuesta.data
        assert "refresh" not in respuesta.data

    def test_password_no_se_devuelve_en_la_respuesta(self, anon_client):
        respuesta = anon_client.post(self.url, self.payload(), format="json")
        assert "password" not in respuesta.data

    def test_envia_correo_de_bienvenida(self, anon_client):
        anon_client.post(self.url, self.payload(), format="json")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["nueva@test.skilly"]

    def test_rechaza_passwords_que_no_coinciden(self, anon_client):
        respuesta = anon_client.post(
            self.url, self.payload(password_confirmacion="Otra123!"), format="json"
        )
        assert respuesta.status_code == 400
        assert "password_confirmacion" in respuesta.data

    def test_rechaza_password_debil(self, anon_client):
        respuesta = anon_client.post(
            self.url,
            self.payload(password="12345", password_confirmacion="12345"),
            format="json",
        )
        assert respuesta.status_code == 400
        assert "password" in respuesta.data

    def test_rechaza_rut_invalido(self, anon_client):
        respuesta = anon_client.post(
            self.url, self.payload(rut="76541230-4"), format="json"
        )
        assert respuesta.status_code == 400
        assert "rut" in respuesta.data

    def test_rechaza_correo_duplicado(self, anon_client, organizacion):
        respuesta = anon_client.post(
            self.url,
            self.payload(email_contacto="organizacion@test.skilly"),
            format="json",
        )
        assert respuesta.status_code == 400
        assert "email_contacto" in respuesta.data

    def test_correo_fallido_no_rompe_el_registro(self, anon_client, monkeypatch):
        """El correo es un efecto secundario: si SES esta caido, el registro
        sigue existiendo y la respuesta sigue siendo 201. Lo que se pierde es
        el correo, no el alta de la organizacion."""
        from django.core.mail import EmailMultiAlternatives

        def explota(self, *args, **kwargs):
            raise OSError("SES caido")

        monkeypatch.setattr(EmailMultiAlternatives, "send", explota)

        respuesta = anon_client.post(self.url, self.payload(), format="json")
        assert respuesta.status_code == 201
        assert Organizacion.objects.filter(nombre="Constructora Nueva SpA").exists()


# ===========================================================================
# Login (1.7)
# ===========================================================================
@pytest.mark.django_db
class TestLogin:
    url = "/api/auth/login/"

    def test_login_por_email_devuelve_tokens(self, anon_client, usuario_organizacion):
        respuesta = anon_client.post(
            self.url,
            {"email": "organizacion@test.skilly", "password": "OrgTest123!"},
            format="json",
        )
        assert respuesta.status_code == 200
        assert "access" in respuesta.data
        assert "refresh" in respuesta.data

    def test_incluye_el_perfil_del_usuario(self, anon_client, usuario_organizacion):
        respuesta = anon_client.post(
            self.url,
            {"email": "organizacion@test.skilly", "password": "OrgTest123!"},
            format="json",
        )
        assert respuesta.data["usuario"]["email"] == "organizacion@test.skilly"

    def test_login_es_case_insensitive_en_el_correo(self, anon_client, usuario_organizacion):
        respuesta = anon_client.post(
            self.url,
            {"email": "ORGANIZACION@test.SKILLY", "password": "OrgTest123!"},
            format="json",
        )
        assert respuesta.status_code == 200

    def test_credenciales_invalidas_dan_401(self, anon_client, usuario_organizacion):
        respuesta = anon_client.post(
            self.url,
            {"email": "organizacion@test.skilly", "password": "Malaclave123!"},
            format="json",
        )
        assert respuesta.status_code == 401

    def test_correo_inexistente_da_401(self, anon_client):
        respuesta = anon_client.post(
            self.url, {"email": "nadie@test.skilly", "password": "OrgTest123!"}, format="json"
        )
        assert respuesta.status_code == 401

    def test_usuario_inactivo_da_mensaje_distinto(self, anon_client, usuario_organizacion):
        usuario_organizacion.is_active = False
        usuario_organizacion.save()
        respuesta = anon_client.post(
            self.url,
            {"email": "organizacion@test.skilly", "password": "OrgTest123!"},
            format="json",
        )
        assert respuesta.status_code == 401
        assert "inactiva" in str(respuesta.data).lower()


# ===========================================================================
# Perfil (1.7, 1.9)
# ===========================================================================
@pytest.mark.django_db
class TestMiPerfil:
    url = "/api/auth/me/"

    def test_requiere_autenticacion(self, anon_client):
        assert anon_client.get(self.url).status_code == 401

    def test_devuelve_los_datos_del_usuario(self, organizacion_client, usuario_organizacion):
        respuesta = organizacion_client.get(self.url)
        assert respuesta.status_code == 200
        assert respuesta.data["email"] == "organizacion@test.skilly"

    def test_no_expone_hash_de_password(self, organizacion_client):
        respuesta = organizacion_client.get(self.url)
        assert "password" not in respuesta.data

    def test_expone_el_id_de_su_organizacion(self, organizacion_client, organizacion):
        """El frontend necesita el id para enlazar con las reservas. Una
        relacion inversa OneToOne no expone `<nombre>_id` en el lado del
        usuario, asi que esto tiene que leer el objeto de la relacion."""
        respuesta = organizacion_client.get(self.url)
        assert respuesta.data["organizacion_id"] == organizacion.pk

    def test_expone_el_id_de_su_perfil_profesional(
        self, profesional_client, profesional
    ):
        respuesta = profesional_client.get(self.url)
        assert respuesta.data["profesional_id"] == profesional.pk

    def test_una_cuenta_sin_perfil_devuelve_null(self, profesional_client):
        """El campo existe siempre, aunque valga None: el frontend no tiene
        que probar si viene la clave antes de leerla."""
        assert profesional_client.get(self.url).data["profesional_id"] is None

    def test_patch_actualiza_nombres(self, organizacion_client):
        respuesta = organizacion_client.patch(
            self.url, {"first_name": "Marcela", "last_name": "Ibáñez"}, format="json"
        )
        assert respuesta.status_code == 200
        assert respuesta.data["last_name"] == "Ibáñez"

    def test_patch_no_puede_cambiar_el_tipo_de_usuario(self, organizacion_client):
        """Un usuario no se autoasigna el rol de admin."""
        respuesta = organizacion_client.patch(self.url, {"tipo": "admin"}, format="json")
        assert respuesta.data["tipo"] != "admin"


# ===========================================================================
# Cambio de contraseña (1.9)
# ===========================================================================
@pytest.mark.django_db
class TestCambiarPassword:
    url = "/api/auth/cambiar-password/"

    def test_cambia_la_contrasena(self, anon_client, usuario_organizacion):
        cliente = anon_client
        cliente.force_authenticate(user=usuario_organizacion)
        respuesta = cliente.post(
            self.url,
            {
                "password_actual": "OrgTest123!",
                "password_nueva": "NuevaClave456!",
                "password_confirmacion": "NuevaClave456!",
            },
            format="json",
        )
        assert respuesta.status_code == 200

    def test_la_nueva_contrasena_sirve_para_hacer_login(
        self, anon_client, usuario_organizacion
    ):
        cliente = anon_client
        cliente.force_authenticate(user=usuario_organizacion)
        cliente.post(
            self.url,
            {
                "password_actual": "OrgTest123!",
                "password_nueva": "NuevaClave456!",
                "password_confirmacion": "NuevaClave456!",
            },
            format="json",
        )
        login = anon_client.post(
            "/api/auth/login/",
            {"email": "organizacion@test.skilly", "password": "NuevaClave456!"},
            format="json",
        )
        assert login.status_code == 200

    def test_exige_la_contrasena_actual(self, organizacion_client):
        respuesta = organizacion_client.post(
            self.url,
            {
                "password_actual": "NoEsLaMia123!",
                "password_nueva": "NuevaClave456!",
                "password_confirmacion": "NuevaClave456!",
            },
            format="json",
        )
        assert respuesta.status_code == 400
        assert "password_actual" in respuesta.data

    def test_rechaza_contrasena_debil(self, organizacion_client):
        respuesta = organizacion_client.post(
            self.url,
            {
                "password_actual": "OrgTest123!",
                "password_nueva": "123",
                "password_confirmacion": "123",
            },
            format="json",
        )
        assert respuesta.status_code == 400


# ===========================================================================
# Recuperación de contraseña (1.10)
# ===========================================================================
@pytest.mark.django_db
class TestPasswordReset:
    url = "/api/auth/password-reset/"
    confirmar = "/api/auth/password-reset/confirmar/"

    def test_envia_correo_con_el_enlace(self, anon_client, usuario_organizacion):
        respuesta = anon_client.post(
            self.url, {"email": "organizacion@test.skilly"}, format="json"
        )
        assert respuesta.status_code == 200
        assert len(mail.outbox) == 1

    def test_correo_desconocido_responde_igual(self, anon_client, usuario_organizacion):
        """Anti-enumeración: no se puede usar el endpoint para averiguar qué
        correos están registrados."""
        con_cuenta = anon_client.post(
            self.url, {"email": "organizacion@test.skilly"}, format="json"
        )
        sin_cuenta = anon_client.post(self.url, {"email": "nadie@test.skilly"}, format="json")

        assert sin_cuenta.status_code == con_cuenta.status_code == 200
        assert sin_cuenta.data == con_cuenta.data
        assert len(mail.outbox) == 1  # solo se envía al que sí existe

    def test_el_token_sirve_una_sola_vez(self, anon_client, usuario_organizacion):
        """El token de Django deja de validar después de cambiar la contraseña:
        por eso el enlace no se puede reutilizar."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes, force_str
        from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(usuario_organizacion.pk))
        token = default_token_generator.make_token(usuario_organizacion)

        datos = {
            "uid": force_str(uid),
            "token": token,
            "password": "ResetClave789!",
            "password_confirmacion": "ResetClave789!",
        }

        primero = anon_client.post(self.confirmar, datos, format="json")
        assert primero.status_code == 200

        segundo = anon_client.post(self.confirmar, datos, format="json")
        assert segundo.status_code == 400

    def test_token_invalido_da_400(self, anon_client, usuario_organizacion):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(usuario_organizacion.pk))
        respuesta = anon_client.post(
            self.confirmar,
            {
                "uid": uid,
                "token": "token-inventado",
                "password": "ResetClave789!",
                "password_confirmacion": "ResetClave789!",
            },
            format="json",
        )
        assert respuesta.status_code == 400

    def test_uid_mal_formado_da_400(self, anon_client):
        respuesta = anon_client.post(
            self.confirmar,
            {
                "uid": "no-es-base64-valido!!!",
                "token": "x",
                "password": "ResetClave789!",
                "password_confirmacion": "ResetClave789!",
            },
            format="json",
        )
        assert respuesta.status_code == 400


# ===========================================================================
# Horarios personalizados (1.9)
# ===========================================================================
@pytest.mark.django_db
class TestHorarios:
    url = "/api/auth/mis-horarios/"

    def test_organizacion_no_gestiona_horarios(self, organizacion_client):
        assert organizacion_client.get(self.url).status_code == 403

    def test_profesional_no_tiene_horarios_al_principio(
        self, profesional_client, profesional
    ):
        respuesta = profesional_client.get(self.url)
        assert respuesta.status_code == 200
        assert respuesta.data == []

    def test_crea_un_horario(self, profesional_client, profesional):
        respuesta = profesional_client.post(
            self.url,
            {"dia_semana": 0, "hora_inicio": "09:00", "hora_fin": "17:00"},
            format="json",
        )
        assert respuesta.status_code == 201
        assert Horario.objects.filter(profesional=profesional).count() == 1

    def test_rechaza_hora_fin_anterior_a_inicio(self, profesional_client, profesional):
        respuesta = profesional_client.post(
            self.url,
            {"dia_semana": 0, "hora_inicio": "17:00", "hora_fin": "09:00"},
            format="json",
        )
        assert respuesta.status_code == 400

    def test_rechaza_bloques_solapados(self, profesional_client, profesional):
        profesional_client.post(
            self.url,
            {"dia_semana": 0, "hora_inicio": "09:00", "hora_fin": "13:00"},
            format="json",
        )
        respuesta = profesional_client.post(
            self.url,
            {"dia_semana": 0, "hora_inicio": "12:00", "hora_fin": "18:00"},
            format="json",
        )
        assert respuesta.status_code == 400

    def test_no_puede_tocar_el_horario_de_otro_profesional(
        self, profesional_client, profesional_otro
    ):
        horario_ajeno = Horario.objects.create(
            profesional=profesional_otro,
            dia_semana=1,
            hora_inicio="09:00",
            hora_fin="17:00",
        )
        respuesta = profesional_client.delete(f"{self.url}{horario_ajeno.pk}/")
        assert respuesta.status_code in (400, 404)
        assert Horario.objects.filter(pk=horario_ajeno.pk).exists()


# ===========================================================================
# Perfil profesional (1.9)
# ===========================================================================
@pytest.mark.django_db
class TestPerfilProfesional:
    url = "/api/auth/mi-perfil-profesional/"

    def test_organizacion_no_tiene_perfil_profesional(self, organizacion_client):
        assert organizacion_client.get(self.url).status_code == 403

    def test_cuenta_sin_perfil_profesional_da_404(self, profesional_client):
        """El usuario es de tipo profesional pero no tiene ficha creada: es un
        404, no un 403. Un 403 diria "prohibido" cuando en realidad no hay nada
        que ver."""
        assert profesional_client.get(self.url).status_code == 404

    def test_profesional_ve_su_perfil(self, profesional_client, profesional):
        respuesta = profesional_client.get(self.url)
        assert respuesta.status_code == 200
        assert respuesta.data["nombre_completo"] == "Juan Pérez"

    def test_incluye_el_estado_de_su_postulacion(self, profesional_client, postulacion):
        respuesta = profesional_client.get(self.url)
        assert respuesta.data["postulacion_estado"] == "Pendiente"

    def test_puede_actualizar_su_biografia(self, profesional_client, profesional):
        respuesta = profesional_client.patch(
            self.url, {"bio": "Diseñador web con 10 años de experiencia."}, format="json"
        )
        assert respuesta.status_code == 200

    def test_no_puede_cambiar_su_estado(self, profesional_client, profesional):
        """El estado lo decide la moderación, no el profesional."""
        respuesta = profesional_client.patch(
            self.url, {"estado": "aprobado"}, format="json"
        )
        assert respuesta.data["estado"] != "aprobado"


# ===========================================================================
# Panel admin: organizaciones y profesionales (1.14)
# ===========================================================================
@pytest.mark.django_db
class TestPanelAdminListados:
    url_orgs = "/api/auth/admin/organizaciones/"
    url_profs = "/api/auth/admin/profesionales/"

    def test_no_admin_no_puede_listar(self, organizacion_client, profesional_client):
        assert organizacion_client.get(self.url_orgs).status_code == 403
        assert profesional_client.get(self.url_profs).status_code == 403

    def test_admin_lista_organizaciones(self, admin_client, organizacion):
        respuesta = admin_client.get(self.url_orgs)
        assert respuesta.status_code == 200
        assert len(respuesta.data) == 1

    def test_busca_organizacion_por_rut_con_puntos(self, admin_client, organizacion):
        """El RUT se guarda normalizado, así que una búsqueda escrita con
        puntos tiene que encontrarla igual."""
        respuesta = admin_client.get(self.url_orgs, {"q": "15.686.734-5"})
        assert respuesta.status_code == 200
        assert len(respuesta.data) == 1

    def test_separa_invitadas_de_registradas(self, admin_client, organizacion, organizacion_invitada):
        respuesta = admin_client.get(self.url_orgs, {"modo": "invitada"})
        assert [o["nombre"] for o in respuesta.data] == ["Empresa Sin Cuenta SpA"]

    def test_admin_lista_profesionales(self, admin_client, profesional):
        respuesta = admin_client.get(self.url_profs)
        assert respuesta.status_code == 200
        assert len(respuesta.data) == 1

    def test_filtra_profesionales_por_estado(self, admin_client, profesional_aprobado):
        assert (
            len(admin_client.get(self.url_profs, {"estado": "aprobado"}).data) == 1
        )
        assert len(admin_client.get(self.url_profs, {"estado": "rechazado"}).data) == 0

    def test_exige_autenticacion(self, anon_client):
        assert anon_client.get(self.url_orgs).status_code == 401
        assert anon_client.get(self.url_profs).status_code == 401