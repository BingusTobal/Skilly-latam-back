"""
Tests del admin de Django. Tickets 1.4, 1.5, 1.11.

El admin de Django es una de las dos superficies de moderación (la otra es la
API del panel), así que necesita la misma cobertura en transiciones: si el
admin permite aprobar una postulación sin comentarios, la regla de negocio
queda rota por ese lado aunque la API la respete.

Estos tests usan `admin_client`, que autentica como superusuario y por lo tanto
sí tiene permisos de `is_staff` (el `admin_client` de DRF no sirve para el
admin de Django: no marca `is_staff`).
"""
import pytest
from django.contrib import admin as django_admin

from apps.postulaciones.models import Certificado, Postulacion

LISTA_POSTULACIONES = "/admin/postulaciones/postulacion/"
LISTA_CERTIFICADOS = "/admin/postulaciones/certificado/"


@pytest.fixture
def admin_web(django_user_model):
    """Superusuario para el admin de Django (necesita is_staff)."""
    return django_user_model.objects.create_superuser(
        email="admin.web@test.skilly",
        password="AdminWeb123!",
        first_name="Admin",
        last_name="Web",
    )


@pytest.fixture
def web_client(client, admin_web):
    client.force_login(admin_web)
    return client


# ===========================================================================
# Registro en el admin
# ===========================================================================
@pytest.mark.django_db
class TestAdminRegistro:
    def test_modelos_estan_registrados(self):
        from apps.postulaciones import admin as admin_postulaciones
        from apps.usuarios import admin as admin_usuarios

        for modelo in (
            admin_usuarios.Organizacion,
            admin_usuarios.Profesional,
            admin_usuarios.Horario,
        ):
            assert modelo in django_admin.site._registry

        assert admin_postulaciones.Postulacion in django_admin.site._registry
        assert admin_postulaciones.Certificado in django_admin.site._registry

    def test_horario_no_busca_por_hora(self):
        """`hora_inicio` es un TimeField y el widget de búsqueda de Django no lo
        maneja: buscar por él revienta la vista de listado del admin."""
        from django.contrib.admin.sites import AdminSite

        from apps.usuarios.admin import HorarioAdmin
        from apps.usuarios.models import Horario

        sitio = AdminSite()
        admin_horario = HorarioAdmin(Horario, sitio)
        assert "hora_inicio" not in admin_horario.search_fields


# ===========================================================================
# PostulacionAdmin
# ===========================================================================
@pytest.mark.django_db
class TestPostulacionAdmin:
    def test_acciones_registradas(self):
        from apps.postulaciones.admin import PostulacionAdmin

        assert "accion_aprobar" in PostulacionAdmin.actions
        assert "accion_devolver" in PostulacionAdmin.actions
        assert "accion_rechazar" in PostulacionAdmin.actions

    def test_aprobar_desde_la_accion(self, web_client, postulacion):
        respuesta = web_client.post(
            LISTA_POSTULACIONES,
            {
                "action": "accion_aprobar",
                "_selected_action": [str(postulacion.pk)],
            },
            follow=True,
        )
        assert respuesta.status_code == 200

        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_APROBADA

    def test_aprobar_no_pasa_comentarios(
        self, web_client, postulacion, monkeypatch
    ):
        """`Postulacion.aprobar()` no acepta comentarios. Si la acción se los
        pasara, reventaría con TypeError al moderar desde el admin."""
        import inspect

        firma = inspect.signature(Postulacion.aprobar)
        assert "comentarios" not in firma.parameters

        respuesta = web_client.post(
            LISTA_POSTULACIONES,
            {
                "action": "accion_aprobar",
                "_selected_action": [str(postulacion.pk)],
            },
            follow=True,
        )
        assert respuesta.status_code == 200
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_APROBADA

    def test_rechazar_sin_comentarios_no_cambia_el_estado(
        self, web_client, postulacion
    ):
        """Rechazar sin comentarios dejaría al profesional sin saber por qué.
        La acción lo salta y lo informa en vez de aplicarlo."""
        respuesta = web_client.post(
            LISTA_POSTULACIONES,
            {
                "action": "accion_rechazar",
                "_selected_action": [str(postulacion.pk)],
            },
            follow=True,
        )
        assert respuesta.status_code == 200

        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE
        assert "sin comentarios" in respuesta.content.decode()

    def test_rechazar_con_comentarios_si_cambia_el_estado(self, web_client, postulacion):
        postulacion.comentarios_admin = "No cubrimos tu especialidad."
        postulacion.save()

        web_client.post(
            LISTA_POSTULACIONES,
            {
                "action": "accion_rechazar",
                "_selected_action": [str(postulacion.pk)],
            },
            follow=True,
        )
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_RECHAZADA

    def test_devolver_con_comentarios(self, web_client, postulacion):
        postulacion.comentarios_admin = "Agrega tu portfolio."
        postulacion.save()

        web_client.post(
            LISTA_POSTULACIONES,
            {
                "action": "accion_devolver",
                "_selected_action": [str(postulacion.pk)],
            },
            follow=True,
        )
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_DEVUELTA

    def test_el_listado_busca_por_rut(self, web_client, postulacion):
        respuesta = web_client.get(LISTA_POSTULACIONES, {"q": "231817460"})
        assert respuesta.status_code == 200
        assert str(postulacion.pk) in respuesta.content.decode()

    def test_abrir_la_ficha_no_falla(self, web_client, postulacion):
        respuesta = web_client.get(f"{LISTA_POSTULACIONES}{postulacion.pk}/change/")
        assert respuesta.status_code == 200


# ===========================================================================
# CertificadoAdmin — la cola separada (R9)
# ===========================================================================
@pytest.mark.django_db
class TestCertificadoAdmin:
    def test_acciones_registradas(self):
        from apps.postulaciones.admin import CertificadoAdmin

        assert "accion_aprobar" in CertificadoAdmin.actions
        assert "accion_rechazar" in CertificadoAdmin.actions

    def test_aprobar_documento_desde_la_accion(self, web_client, certificado_sin_revisar):
        web_client.post(
            LISTA_CERTIFICADOS,
            {
                "action": "accion_aprobar",
                "_selected_action": [str(certificado_sin_revisar.pk)],
            },
            follow=True,
        )
        certificado_sin_revisar.refresh_from_db()
        assert certificado_sin_revisar.estado == Certificado.ESTADO_APROBADO

    def test_la_accion_omite_linkedin(self, web_client, certificado_linkedin):
        """LinkedIn ya nace verificado: la acción debe saltarlo y avisar, en
        lugar de reventar con una ValidationError."""
        respuesta = web_client.post(
            LISTA_CERTIFICADOS,
            {
                "action": "accion_aprobar",
                "_selected_action": [str(certificado_linkedin.pk)],
            },
            follow=True,
        )
        assert respuesta.status_code == 200

        certificado_linkedin.refresh_from_db()
        assert certificado_linkedin.estado == Certificado.ESTADO_VERIFICADO_AUTOMATICO
        assert "omitidos" in respuesta.content.decode()

    def test_rechazar_desde_la_accion(self, web_client, certificado_sin_revisar):
        certificado_sin_revisar.comentario_revisor = "Documento ilegible."
        certificado_sin_revisar.save()

        web_client.post(
            LISTA_CERTIFICADOS,
            {
                "action": "accion_rechazar",
                "_selected_action": [str(certificado_sin_revisar.pk)],
            },
            follow=True,
        )
        certificado_sin_revisar.refresh_from_db()
        assert certificado_sin_revisar.estado == Certificado.ESTADO_RECHAZADO
        assert certificado_sin_revisar.comentario_revisor == "Documento ilegible."

    def test_aprobar_certificado_no_aprueba_la_postulacion(
        self, web_client, postulacion, certificado_sin_revisar
    ):
        web_client.post(
            LISTA_CERTIFICADOS,
            {
                "action": "accion_aprobar",
                "_selected_action": [str(certificado_sin_revisar.pk)],
            },
            follow=True,
        )
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE

    def test_el_estado_de_linkedin_es_solo_lectura(self, web_client, certificado_linkedin):
        """Un certificado verificado automáticamente no debe poder cambiarse de
        estado a mano desde la ficha."""
        from django.contrib.admin.sites import AdminSite

        from apps.postulaciones.admin import CertificadoAdmin

        sitio = AdminSite()
        admin_cert = CertificadoAdmin(Certificado, sitio)
        assert "estado" in admin_cert.get_readonly_fields(None, certificado_linkedin)

    def test_un_documento_normal_si_puede_editarse_el_estado(self, certificado_sin_revisar):
        from django.contrib.admin.sites import AdminSite

        from apps.postulaciones.admin import CertificadoAdmin

        sitio = AdminSite()
        admin_cert = CertificadoAdmin(Certificado, sitio)
        assert "estado" not in admin_cert.get_readonly_fields(None, certificado_sin_revisar)


# ===========================================================================
# UsuariosAdmin
# ===========================================================================
@pytest.mark.django_db
class TestUsuariosAdmin:
    def test_el_password_no_aparece_en_la_ficha(self, web_client, organizacion):
        html = web_client.get(
            f"/admin/usuarios/usuario/{organizacion.usuario_id}/change/"
        ).content.decode()
        assert "pbkdf2_sha256" not in html

    def test_organizacion_sin_usuario_se_abre(self, web_client, organizacion_invitada):
        """D7: la organización invitada no tiene usuario, y el admin no debe
        reventar al abrirla."""
        respuesta = web_client.get(
            f"/admin/usuarios/organizacion/{organizacion_invitada.pk}/change/"
        )
        assert respuesta.status_code == 200

    def test_profesional_muestra_su_postulacion(self, web_client, postulacion):
        html = web_client.get(
            f"/admin/usuarios/profesional/{postulacion.profesional_id}/change/"
        ).content.decode()
        assert "postulaci" in html.lower()

    def test_horario_se_abre(self, web_client, profesional):
        from apps.usuarios.models import Horario

        horario = Horario.objects.create(
            profesional=profesional,
            dia_semana=0,
            hora_inicio="09:00",
            hora_fin="17:00",
        )
        respuesta = web_client.get(f"/admin/usuarios/horario/{horario.pk}/change/")
        assert respuesta.status_code == 200