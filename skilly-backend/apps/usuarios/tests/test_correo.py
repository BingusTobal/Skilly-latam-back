"""
Tests del envío de correo. Tickets 1.6, 1.10, 1.12.

La regla que más importa acá, y la que más fácil se rompe: un correo que falla
NO puede hacer fallar la operación de negocio. La postulación ya está
persistida cuando se manda el correo; si SES está caído, lo que se pierde es el
correo, no el alta.

Hay un test por función para eso, y uno que verifica que el contenido del
correo de certificado no insinúa que la postulación también fue rechazada (R9).
"""
import logging

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives

from apps.usuarios.correo import (
    enviar_bienvenida_organizacion,
    enviar_certificado_rechazado,
    enviar_password_reset,
    enviar_postulacion_aprobada,
    enviar_postulacion_devuelta,
    enviar_postulacion_recibida,
    enviar_postulacion_rechazada,
)


@pytest.fixture
def ses_caido(monkeypatch):
    """Simula que el backend de correo revienta."""

    def explota(self, *args, **kwargs):
        raise OSError("SES no disponible")

    monkeypatch.setattr(EmailMultiAlternatives, "send", explota)


# ===========================================================================
# Los dos formatos
# ===========================================================================
@pytest.mark.django_db
class TestFormatos:
    def test_envia_texto_y_html(self, organizacion):
        enviar_bienvenida_organizacion(organizacion)
        mensaje = mail.outbox[0]
        assert mensaje.body  # texto plano
        assert mensaje.alternatives  # y la versión html

    def test_el_html_es_el_primer_alternativo(self, organizacion):
        enviar_bienvenida_organizacion(organizacion)
        contenido, tipo = mail.outbox[0].alternatives[0]
        assert tipo == "text/html"
        assert "<html" in contenido

    def test_el_html_arranca_con_la_base_compartida(self, organizacion):
        """Todas las plantillas heredan de base.html: si esa se rompe, se rompen
        los ocho correos."""
        enviar_bienvenida_organizacion(organizacion)
        contenido, _ = mail.outbox[0].alternatives[0]
        assert "Skilly Latam" in contenido

    def test_envia_desde_el_remitente_configurado(self, organizacion):
        enviar_bienvenida_organizacion(organizacion)
        assert mail.outbox[0].from_email


# ===========================================================================
# Un fallo de correo no rompe nada
# ===========================================================================
@pytest.mark.django_db
class TestFalloDeCorreo:
    def test_devuelve_false_no_levanta(self, organizacion, ses_caido):
        assert enviar_bienvenida_organizacion(organizacion) is False

    def test_se_loguea_el_error(self, organizacion, ses_caido, caplog):
        """Un fallo silencioso es un fallo que nadie va a investigar: tiene que
        quedar en el log, con el traceback para poder diagnosticarlo."""
        with caplog.at_level(logging.ERROR, logger="apps.usuarios.correo"):
            enviar_bienvenida_organizacion(organizacion)

        assert "Fallo al enviar" in caplog.text
        assert "SES no disponible" in caplog.text

    def test_sin_destinatario_no_revienta(self, db, ses_caido):
        from apps.usuarios.models import Organizacion

        # Una organización siempre tiene email_contacto, así que se prueba el
        # camino con un postulacion sin usuario.
        assert (
            __import__(
                "apps.usuarios.correo", fromlist=["_enviar"]
            )._enviar("asunto", "cuerpo", [])
            is False
        )

    def test_el_registro_sobrevive_al_correo_caido(
        self, anon_client, ses_caido
    ):
        """La prueba de fuego: SES caído, registro exitoso."""
        respuesta = anon_client.post(
            "/api/auth/registro-organizacion/",
            {
                "nombre": "Constructora SpA",
                "giro": "Construcción",
                "nombre_contacto": "Marcela Ibáñez",
                "email_contacto": "sin.correo@test.skilly",
                "telefono": "+56912345678",
                "rut": "18765321-5",
                "password": "OrgTest123!",
                "password_confirmacion": "OrgTest123!",
            },
            format="json",
        )
        assert respuesta.status_code == 201

        from apps.usuarios.models import Organizacion

        assert Organizacion.objects.filter(
            email_contacto="sin.correo@test.skilly"
        ).exists()


# ===========================================================================
# Contenido de cada correo
# ===========================================================================
@pytest.mark.django_db
class TestContenido:
    def test_bienvenida_saluda_con_el_nombre_del_contacto(self, organizacion):
        enviar_bienvenida_organizacion(organizacion)
        assert "Marcela" in mail.outbox[0].body

    def test_password_reset_incluye_el_enlace(self, usuario_organizacion):
        enviar_password_reset(
            usuario_organizacion, "https://skilly.cl/restablecer/abc/token"
        )
        assert "https://skilly.cl/restablecer/abc/token" in mail.outbox[0].body

    def test_password_reset_advierte_si_no_fue_el_usuario(self, usuario_organizacion):
        """Sin este aviso, alguien que receives este correo por error entra en
        pánico."""
        enviar_password_reset(usuario_organizacion, "https://skilly.cl/x")
        cuerpo = mail.outbox[0].body.lower()
        assert "no solicitaste" in cuerpo

    def test_acuse_de_recibo(self, postulacion):
        enviar_postulacion_recibida(postulacion)
        assert mail.outbox[0].to == ["profesional@test.skilly"]
        assert "recibimos" in mail.outbox[0].body.lower()

    def test_aprobada_no_mezcla_el_estado_de_los_documentos(self, postulacion):
        """R9: el correo de aprobación no debe dar a entender que los
        certificados quedaron aprobados también."""
        enviar_postulacion_aprobada(postulacion)
        cuerpo = mail.outbox[0].body.lower()
        assert "aprobada" in cuerpo
        # Lo que SÍ puede decir es que hay una revisión aparte.
        assert "documento" in cuerpo or "certificado" in cuerpo

    def test_devuelta_incluye_los_comentarios_del_admin(
        self, postulacion, usuario_admin
    ):
        """Sin los comentarios en el correo, el profesional no sabe qué
        corregir hasta que vuelve a la plataforma."""
        postulacion.devolver(usuario_admin, "Adjunta tu portfolio.")
        enviar_postulacion_devuelta(postulacion)

        cuerpo = mail.outbox[0].body
        assert "Adjunta tu portfolio." in cuerpo
        assert "Adjunta tu portfolio." in mail.outbox[0].alternatives[0][0]

    def test_rechazada_incluye_el_motivo(self, postulacion, usuario_admin):
        postulacion.rechazar(usuario_admin, "No cubrimos tu especialidad.")
        enviar_postulacion_rechazada(postulacion)
        assert "No cubrimos tu especialidad." in mail.outbox[0].body

    def test_certificado_rechazado_aclara_que_es_independiente(
        self, certificado_sin_revisar, usuario_admin
    ):
        """R9 en el correo: si no se aclara, el profesional cree que le
        rechazaron la postulación entera."""
        certificado_sin_revisar.rechazar(usuario_admin, "El PDF está ilegible.")
        enviar_certificado_rechazado(certificado_sin_revisar)

        cuerpo = mail.outbox[0].body
        assert "Título profesional" in cuerpo
        assert "El PDF está ilegible." in cuerpo
        assert "independiente" in cuerpo.lower()

    def test_certificado_rechazado_no_usa_el_nombre_de_la_postulacion(
        self, certificado_sin_revisar
    ):
        """El correo es sobre el documento, no sobre la postulación."""
        enviar_certificado_rechazado(certificado_sin_revisar)
        assert "postulación" not in mail.outbox[0].subject.lower()

    def test_los_asuntos_son_distintos_por_tipo(self, postulacion, usuario_admin):
        vistos = set()
        enviar_postulacion_recibida(postulacion)
        vistos.add(mail.outbox[-1].subject)
        postulacion.aprobar(usuario_admin)
        enviar_postulacion_aprobada(postulacion)
        vistos.add(mail.outbox[-1].subject)
        postulacion.comentarios_admin = "Corregir."
        enviar_postulacion_devuelta(postulacion)
        vistos.add(mail.outbox[-1].subject)

        assert len(vistos) == 3