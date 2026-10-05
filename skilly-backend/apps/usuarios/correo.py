"""
Envío de correos. Tickets 1.6, 1.10, 1.12.

Una regla que atraviesa TODO este módulo: un correo que falla NUNCA puede
hacer fallar la operación que ya se persistió. El profesionaloloadzó su
postulación y el estado es correcto aunque SES esté caído; perder el correo
es un problema operativo, devolver un 500 al usuario que yaikesió un trabajo
es un problema de producto.

Por eso cada función envuelve el `send_mail` en su propio `try/except`,
loguea el error y sigue.

En desarrollo, `EMAIL_BACKEND` es `console.EmailBackend` (settings), así que
estas funciones no necesitan ni credenciales AWS ni internet para probarse.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def _enviar(asunto, cuerpo_texto, destinatarios, plantilla_html=None, contexto=None):
    """Envía un correo multialternativa, tolerando fallos.

    Devuelve True si se envió, False si falló. El resultado se loguea, pero no
    se propaga: la respuesta al usuario no depende del correo.
    """
    if not destinatarios:
        logger.warning("Correo '%s' sin destinatarios; no se envía.", asunto)
        return False

    remitente = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "no-reply@skilly.cl"

    try:
        mensaje = EmailMultiAlternatives(
            subject=asunto,
            body=cuerpo_texto,
            from_email=remitente,
            to=list(destinatarios),
        )
        if plantilla_html and contexto is not None:
            mensaje.attach_alternative(plantilla_html, "text/html")

        mensaje.send(fail_silently=False)
        logger.info("Correo '%s' enviado a %s.", asunto, ", ".join(destinatarios))
        return True

    except Exception:
        # A propósito un except amplio: SMTP, SES y los timeouts lanzan tipos
        # distintos, y ninguno debe romper la operación de negocio.
        logger.exception("Fallo al enviar el correo '%s'.", asunto)
        return False


# ---------------------------------------------------------------------------
# 1.6 Alta de organización
# ---------------------------------------------------------------------------
def enviar_bienvenida_organizacion(organizacion):
    from django.template.loader import render_to_string

    contexto = {
        "nombre": organizacion.nombre_contacto or organizacion.nombre,
        "organizacion": organizacion,
    }
    asunto = "Bienvenido a Skilly Latam"
    cuerpo = render_to_string("emails/bienvenida_organizacion.txt", contexto)
    html = render_to_string("emails/bienvenida_organizacion.html", contexto)

    return _enviar(
        asunto, cuerpo, [organizacion.email_contacto], plantilla_html=html, contexto=contexto
    )


# ---------------------------------------------------------------------------
# 1.10 Recuperación de contraseña
# ---------------------------------------------------------------------------
def enviar_password_reset(usuario, enlace):
    from django.template.loader import render_to_string

    nombre = usuario.first_name or usuario.email
    contexto = {"nombre": nombre, "enlace": enlace, "usuario": usuario}

    cuerpo = render_to_string("emails/password_reset.txt", contexto)
    html = render_to_string("emails/password_reset.html", contexto)

    return _enviar(
        "Restablece tu contraseña de Skilly",
        cuerpo,
        [usuario.email],
        plantilla_html=html,
        contexto=contexto,
    )


# ---------------------------------------------------------------------------
# Postulaciones. Todas se disparan desde el panel admin (1.11 y 1.12).
# ---------------------------------------------------------------------------
def _destinatario_postulacion(postulacion):
    """Email del profesional de la postulación, o None si no tiene usuario."""
    usuario = postulacion.profesional.usuario
    return usuario.email if usuario else None


def enviar_postulacion_recibida(postulacion):
    """Acuse de recibo. No lleva datos de la postulación, solo el nombre."""
    from django.template.loader import render_to_string

    contexto = {"nombre": postulacion.profesional.nombre_completo}
    cuerpo = render_to_string("emails/postulacion_recibida.txt", contexto)
    html = render_to_string("emails/postulacion_recibida.html", contexto)

    return _enviar(
        "Recibimos tu postulación",
        cuerpo,
        [_destinatario_postulacion(postulacion)],
        plantilla_html=html,
        contexto=contexto,
    )


def enviar_postulacion_aprobada(postulacion):
    """Aprobación. NO menciona los certificados: es una cola separada (R9)."""
    from django.template.loader import render_to_string

    contexto = {"nombre": postulacion.profesional.nombre_completo}
    cuerpo = render_to_string("emails/postulacion_aprobada.txt", contexto)
    html = render_to_string("emails/postulacion_aprobada.html", contexto)

    return _enviar(
        "Tu postulación fue aprobada",
        cuerpo,
        [_destinatario_postulacion(postulacion)],
        plantilla_html=html,
        contexto=contexto,
    )


def enviar_postulacion_devuelta(postulacion):
    """Devuelta para corrección. Incluye SIEMPRE los comentarios del admin:
    sin ellos el profesional no sabe qué arreglar."""
    from django.template.loader import render_to_string

    contexto = {
        "nombre": postulacion.profesional.nombre_completo,
        "comentarios": postulacion.comentarios_admin,
    }
    cuerpo = render_to_string("emails/postulacion_devuelta.txt", contexto)
    html = render_to_string("emails/postulacion_devuelta.html", contexto)

    return _enviar(
        "Tu postulación necesita correcciones",
        cuerpo,
        [_destinatario_postulacion(postulacion)],
        plantilla_html=html,
        contexto=contexto,
    )


def enviar_postulacion_rechazada(postulacion):
    """Rechazo. También con comentarios: son obligatorios para rechazar."""
    from django.template.loader import render_to_string

    contexto = {
        "nombre": postulacion.profesional.nombre_completo,
        "comentarios": postulacion.comentarios_admin,
    }
    cuerpo = render_to_string("emails/postulacion_rechazada.txt", contexto)
    html = render_to_string("emails/postulacion_rechazada.html", contexto)

    return _enviar(
        "Tu postulación no fue aprobada",
        cuerpo,
        [_destinatario_postulacion(postulacion)],
        plantilla_html=html,
        contexto=contexto,
    )


def enviar_certificado_rechazado(certificado, comentario=""):
    """Rechazo de un documento (1.11). Cola separada de la postulación.

    El texto aclara que el estado del documento no determina el de la
    postulación: evita que el profesional crea que le rechazaron entero.
    """
    from django.template.loader import render_to_string

    postulacion = certificado.postulacion
    contexto = {
        "nombre": postulacion.profesional.nombre_completo,
        "certificado": certificado,
        "comentarios": comentario or certificado.comentario_revisor,
    }
    cuerpo = render_to_string("emails/certificado_rechazado.txt", contexto)
    html = render_to_string("emails/certificado_rechazado.html", contexto)

    return _enviar(
        "Un documento tuyo no fue aprobado",
        cuerpo,
        [_destinatario_postulacion(postulacion)],
        plantilla_html=html,
        contexto=contexto,
    )