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


# ===========================================================================
# Fixtures del Sprint 1: organizaciones, profesionales y postulaciones
# ===========================================================================
# RUTs con dígito verificador real (módulo 11). Los de los mockups son
# inválidos y no sirven para probar: ver docs/CONTEXTO-ARQUITECTURA.docx 9.5.

RUT_ORGANIZACION_VALIDO = "15686734-5"
RUT_ORGANIZACION_VALIDO_2 = "18765321-5"
RUT_PROFESIONAL_VALIDO = "23181746-0"
RUT_PROFESIONAL_VALIDO_2 = "24918073-K"
RUT_INVALIDO = "76541230-4"


@pytest.fixture
def organizacion(db, usuario_organizacion):
    from apps.usuarios.models import Organizacion

    return Organizacion.objects.create(
        usuario=usuario_organizacion,
        nombre="Constructora Prueba Ltda.",
        giro="Construcción",
        nombre_contacto="Marcela Ibáñez",
        email_contacto="organizacion@test.skilly",
        telefono="+56912345678",
        rut=RUT_ORGANIZACION_VALIDO,
    )


@pytest.fixture
def organizacion_invitada(db):
    """Organización creada por una reserva sin cuenta (D7): sin usuario."""
    from apps.usuarios.models import Organizacion

    return Organizacion.objects.create(
        nombre="Empresa Sin Cuenta SpA",
        nombre_contacto="Contacto Invitado",
        email_contacto="invitado@test.skilly",
        rut=RUT_ORGANIZACION_VALIDO_2,
        modo=Organizacion.MODO_INVITADA,
    )


@pytest.fixture
def profesional(db, usuario_profesional):
    """Profesional en estado 'postulando'."""
    from apps.usuarios.models import Profesional

    return Profesional.objects.create(
        usuario=usuario_profesional,
        nombre_completo="Juan Pérez",
        rut=RUT_PROFESIONAL_VALIDO,
        telefono="+56987654321",
        ciudad="Santiago",
        estado=Profesional.ESTADO_POSTULANDO,
    )


@pytest.fixture
def profesional_aprobado(db, profesional):
    """Profesional habilitado para publicar servicios."""
    from apps.usuarios.models import Profesional

    profesional.estado = Profesional.ESTADO_APROBADO
    profesional.save()
    return profesional


@pytest.fixture
def profesional_otro(db):
    """Segundo profesional, para probar que nadie toca datos ajenos."""
    from django.contrib.auth import get_user_model

    from apps.usuarios.models import Profesional

    Usuario = get_user_model()
    usuario = Usuario.objects.create_user(
        email="otro@test.skilly",
        password="OtroTest123!",
        first_name="María",
        last_name="González",
        tipo=Usuario.TIPO_PROFESIONAL,
    )
    return Profesional.objects.create(
        usuario=usuario,
        nombre_completo="María González",
        rut=RUT_PROFESIONAL_VALIDO_2,
        estado=Profesional.ESTADO_POSTULANDO,
    )


@pytest.fixture
def postulacion(db, profesional):
    from apps.postulaciones.models import Postulacion

    return Postulacion.objects.create(
        profesional=profesional,
        experiencia="10 años de experiencia en diseño web.",
        especialidad="Diseño web",
    )


@pytest.fixture
def certificado_sin_revisar(db, postulacion):
    """Documento adjunto esperando moderación manual."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.postulaciones.models import Certificado

    archivo = SimpleUploadedFile(
        "titulo.pdf", b"%PDF-1.4 contenido de prueba", content_type="application/pdf"
    )
    return Certificado.objects.create(
        postulacion=postulacion,
        tipo=Certificado.TIPO_OTRO,
        nombre="Título profesional",
        archivo=archivo,
        estado=Certificado.ESTADO_SIN_REVISOR,
    )


@pytest.fixture
def certificado_linkedin(db, postulacion):
    """Perfil de LinkedIn: verificado por formato de URL, sin moderar."""
    from apps.postulaciones.models import Certificado

    return Certificado.objects.create(
        postulacion=postulacion,
        tipo=Certificado.TIPO_LINKEDIN,
        nombre="Perfil de LinkedIn — Juan Pérez",
        enlace="https://www.linkedin.com/in/juan-perez",
        estado=Certificado.ESTADO_VERIFICADO_AUTOMATICO,
    )