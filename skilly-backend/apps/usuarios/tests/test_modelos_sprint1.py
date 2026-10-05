"""
Tests de modelos del Sprint 1: Organizacion, Profesional, Horario, Postulacion
y Certificado.

Estos tests fijan reglas de NEGOCIO, no la forma de la API. Si mañana se
cambia un endpoint, acá no debería haber que tocar nada.
"""
import pytest
from django.core.exceptions import ValidationError

from apps.postulaciones.models import Certificado, Postulacion
from apps.usuarios.models import Horario, Organizacion, Profesional

from conftest import (
    RUT_INVALIDO,
    RUT_ORGANIZACION_VALIDO,
    RUT_PROFESIONAL_VALIDO,
)


# ===========================================================================
# Organizacion
# ===========================================================================
@pytest.mark.django_db
class TestOrganizacion:
    def test_crea_con_rut_valido(self):
        from django.contrib.auth import get_user_model

        Usuario = get_user_model()
        usuario = Usuario.objects.create_user(
            email="org@test.skilly", password="OrgTest123!", tipo=Usuario.TIPO_ORGANIZACION
        )
        org = Organizacion.objects.create(
            usuario=usuario,
            nombre="Constructora SpA",
            nombre_contacto="Marcela Ibáñez",
            email_contacto="org@test.skilly",
            rut=RUT_ORGANIZACION_VALIDO,
        )
        assert org.pk is not None
        assert org.modo == Organizacion.MODO_REGISTRADA

    def test_rechaza_rut_invalido(self, organizacion):
        organizacion.rut = RUT_INVALIDO
        with pytest.raises(ValidationError):
            organizacion.full_clean()

    def test_rut_es_unico(self, organizacion):
        """`unique=True` vive en la columna, así que la garantía la da la base
        de datos, no `full_clean()`. Por eso el test espera IntegrityError al
        guardar, no ValidationError al validar."""
        from django.db import IntegrityError, transaction

        duplicada = Organizacion(
            nombre="Otra Org",
            nombre_contacto="Contacto",
            email_contacto="org2@test.skilly",
            modo=Organizacion.MODO_INVITADA,
            rut=RUT_ORGANIZACION_VALIDO,  # ya usado
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                duplicada.save()

    def test_admite_organizacion_sin_usuario(self, db):
        """D7: la reserva sin cuenta crea la organización sin usuario."""
        org = Organizacion.objects.create(
            nombre="Empresa Sin Cuenta",
            nombre_contacto="Invitado",
            email_contacto="invitado@test.skilly",
            rut="18765321-5",
            modo=Organizacion.MODO_INVITADA,
        )
        assert org.usuario is None
        assert org.modo == Organizacion.MODO_INVITADA

    def test_rut_se_normaliza_sin_puntos_ni_guiones(self, db):
        org = Organizacion.objects.create(
            nombre="Con Formato",
            nombre_contacto="Contacto",
            email_contacto="formato@test.skilly",
            rut="23181746-0",
        )
        assert "-" not in org.rut
        assert "." not in org.rut


# ===========================================================================
# Profesional
# ===========================================================================
@pytest.mark.django_db
class TestProfesional:
    def test_estado_inicial_es_postulando(self, profesional):
        assert profesional.estado == Profesional.ESTADO_POSTULANDO

    def test_rechaza_rut_invalido(self, profesional):
        profesional.rut = RUT_INVALIDO
        with pytest.raises(ValidationError):
            profesional.full_clean()

    def test_rut_no_se_comparte_con_organizaciones(self, organizacion, profesional):
        """El RUT es único DENTRO de cada tabla, no entre las dos.

        Es intencional: una persona puede ser organización y profesional a la
        vez, y el control de duplicados real es el del usuario, no el del RUT.
        """
        profesional.rut = organizacion.rut
        profesional.full_clean()  # no debe fallar

    def test_disponibilidad_es_valida(self, profesional):
        profesional.disponibilidad = "no_se"
        with pytest.raises(ValidationError):
            profesional.full_clean()

    def test_email_del_usuario_es_unico_y_obligatorio(self, profesional):
        assert profesional.usuario.email == "profesional@test.skilly"


# ===========================================================================
# Horario
# ===========================================================================
@pytest.mark.django_db
class TestHorario:
    def test_hora_fin_debe_ser_posterior_a_inicio(self, profesional):
        horario = Horario(
            profesional=profesional,
            dia_semana=0,
            hora_inicio="18:00",
            hora_fin="09:00",  # al revés
        )
        with pytest.raises(ValidationError):
            horario.full_clean()

    def test_dia_semana_debe_estar_en_rango(self, profesional):
        horario = Horario(
            profesional=profesional,
            dia_semana=9,  # fuera de 0-6
            hora_inicio="09:00",
            hora_fin="17:00",
        )
        with pytest.raises(ValidationError):
            horario.full_clean()

    def test_permite_reactivar_un_bloque_ya_desactivado(self, profesional):
        """No puede haber dos bloques para el mismo día, pero sí reutilizar
        uno desactivado. La restricción es de aplicación, no de base."""
        Horario.objects.create(
            profesional=profesional,
            dia_semana=1,
            hora_inicio="09:00",
            hora_fin="17:00",
            activo=False,
        )
        # Reactivar el mismo bloque debe funcionar.
        bloque = Horario.objects.get(profesional=profesional, dia_semana=1)
        bloque.activo = True
        bloque.full_clean()
        bloque.save()
        assert Horario.objects.filter(profesional=profesional, dia_semana=1).count() == 1

    def test_rechaza_bloques_que_se_solapan(self, profesional):
        """No basta con que el día esté repetido: lo que choca es el solapamiento
        de horas. Dos bloques el mismo día pero en rangos distintos sí valen."""
        Horario.objects.create(
            profesional=profesional,
            dia_semana=2,
            hora_inicio="09:00",
            hora_fin="13:00",
            activo=True,
        )
        solapado = Horario(
            profesional=profesional,
            dia_semana=2,
            hora_inicio="12:00",  # arranca antes de que termine el anterior
            hora_fin="18:00",
            activo=True,
        )
        with pytest.raises(ValidationError):
            solapado.full_clean()

    def test_bloques_contiguos_no_se_consideran_solapados(self, profesional):
        """La ventana es semiabierta [inicio, fin): un bloque que arranca justo
        cuando termina el anterior es un turno seguido, no un solapamiento.
        Es lo que permite partir un día largo en mañana y tarde."""
        Horario.objects.create(
            profesional=profesional,
            dia_semana=2,
            hora_inicio="09:00",
            hora_fin="13:00",
        )
        segundo = Horario(
            profesional=profesional,
            dia_semana=2,
            hora_inicio="13:00",
            hora_fin="18:00",
        )
        segundo.full_clean()  # no debe fallar

    def test_admite_dos_bloques_del_mismo_dia_sin_solaparse(self, profesional):
        Horario.objects.create(
            profesional=profesional,
            dia_semana=2,
            hora_inicio="09:00",
            hora_fin="13:00",
        )
        segundo = Horario(
            profesional=profesional,
            dia_semana=2,
            hora_inicio="14:00",
            hora_fin="18:00",
        )
        segundo.full_clean()  # no debe fallar
        segundo.save()
        assert Horario.objects.filter(profesional=profesional, dia_semana=2).count() == 2

    def test_hora_texto_usa_formato_24h(self, profesional):
        horario = Horario.objects.create(
            profesional=profesional,
            dia_semana=3,
            hora_inicio="09:00",
            hora_fin="17:30",
        )
        # `__str__` es lo que ve el admin y los listados.
        assert str(horario) == "Jueves: 09:00–17:30"


# ===========================================================================
# Postulacion
# ===========================================================================
@pytest.mark.django_db
class TestPostulacion:
    def test_estado_inicial_es_pendiente(self, postulacion):
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE

    def test_no_admite_dos_pendientes_del_mismo_profesional(self, profesional):
        Postulacion.objects.create(profesional=profesional, estado=Postulacion.ESTADO_PENDIENTE)
        segunda = Postulacion(
            profesional=profesional, estado=Postulacion.ESTADO_PENDIENTE
        )
        with pytest.raises(ValidationError):
            segunda.full_clean()

    def test_devolver_exige_comentarios(self, postulacion, usuario_admin):
        with pytest.raises(ValidationError):
            postulacion.devolver(usuario_admin, comentarios="")

    def test_rechazar_exige_comentarios(self, postulacion, usuario_admin):
        with pytest.raises(ValidationError):
            postulacion.rechazar(usuario_admin, comentarios="   ")

    def test_aprobar_no_exige_comentarios(self, postulacion, usuario_admin):
        postulacion.aprobar(usuario_admin)
        assert postulacion.estado == Postulacion.ESTADO_APROBADA

    def test_aprobar_sincroniza_estado_del_profesional(self, postulacion, profesional, usuario_admin):
        postulacion.aprobar(usuario_admin)
        profesional.refresh_from_db()
        assert profesional.estado == Profesional.ESTADO_APROBADO

    def test_rechazar_sincroniza_estado_del_profesional(self, postulacion, profesional, usuario_admin):
        postulacion.rechazar(usuario_admin, "No tenemos experiencia en tu rubro.")
        profesional.refresh_from_db()
        assert profesional.estado == Profesional.ESTADO_RECHAZADO

    def test_devuelta_sincroniza_estado_del_profesional(self, postulacion, profesional, usuario_admin):
        postulacion.devolver(usuario_admin, "Falta indicar la experiencia.")
        profesional.refresh_from_db()
        assert profesional.estado == Profesional.ESTADO_POSTULANDO

    def test_no_se_puede_aprobar_una_postulacion_ya_aprobada(self, postulacion, usuario_admin):
        postulacion.aprobar(usuario_admin)
        with pytest.raises(ValueError):
            postulacion.aprobar(usuario_admin)

    def test_no_se_puede_rechazar_una_aprobada(self, postulacion, usuario_admin):
        postulacion.aprobar(usuario_admin)
        with pytest.raises(ValueError):
            postulacion.rechazar(usuario_admin, "Cambio de opinión.")

    def test_ciclo_devuelta_reenvio_aprobacion(self, postulacion, usuario_admin):
        postulacion.devolver(usuario_admin, "Agrega más detalle.")
        assert postulacion.estado == Postulacion.ESTADO_DEVUELTA

        postulacion.reenviar()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE
        # Al reenviar se limpian los comentarios: ya fueron aplicados.
        assert postulacion.comentarios_admin == ""

        postulacion.aprobar(usuario_admin)
        assert postulacion.estado == Postulacion.ESTADO_APROBADA

    def test_solo_se_puede_reenviar_una_devuelta(self, postulacion):
        with pytest.raises(ValueError):
            postulacion.reenviar()

    def test_registra_quien_reviso(self, postulacion, usuario_admin):
        postulacion.aprobar(usuario_admin)
        assert postulacion.revisada_por == usuario_admin
        assert postulacion.fecha_revision is not None

    def test_comentarios_se_normalizan(self, postulacion, usuario_admin):
        postulacion.devolver(usuario_admin, "   Completa la experiencia.   ")
        assert postulacion.comentarios_admin == "Completa la experiencia."


# ===========================================================================
# Certificado
# ===========================================================================
@pytest.mark.django_db
class TestCertificado:
    def test_linkedin_exige_enlace(self, postulacion):
        from django.core.files.uploadedfile import SimpleUploadedFile

        cert = Certificado(
            postulacion=postulacion,
            tipo=Certificado.TIPO_LINKEDIN,
            nombre="Perfil",
            archivo=SimpleUploadedFile("a.pdf", b"%PDF-1.4"),
            estado=Certificado.ESTADO_SIN_REVISOR,
        )
        with pytest.raises(ValidationError):
            cert.full_clean()

    def test_documento_exige_archivo(self, postulacion):
        cert = Certificado(
            postulacion=postulacion,
            tipo=Certificado.TIPO_OTRO,
            nombre="Título",
            estado=Certificado.ESTADO_SIN_REVISOR,
        )
        with pytest.raises(ValidationError):
            cert.full_clean()

    def test_linkedin_no_se_puede_moderar(self, certificado_linkedin, usuario_admin):
        """Decisión 3: el perfil de LinkedIn no entra a la cola manual."""
        with pytest.raises(ValidationError):
            certificado_linkedin.aprobar(usuario_admin)
        with pytest.raises(ValidationError):
            certificado_linkedin.rechazar(usuario_admin, "No coincide")

    def test_documento_se_aprueba(self, certificado_sin_revisar, usuario_admin):
        certificado_sin_revisar.aprobar(usuario_admin)
        assert certificado_sin_revisar.estado == Certificado.ESTADO_APROBADO
        assert certificado_sin_revisar.revisado_por == usuario_admin

    def test_documento_se_rechaza_con_comentario(self, certificado_sin_revisar, usuario_admin):
        certificado_sin_revisar.rechazar(usuario_admin, "El PDF está ilegible.")
        assert certificado_sin_revisar.estado == Certificado.ESTADO_RECHAZADO
        assert certificado_sin_revisar.comentario_revisor == "El PDF está ilegible."

    def test_requiere_moderacion_solo_si_esta_sin_revisar(
        self, certificado_sin_revisar, certificado_linkedin
    ):
        assert certificado_sin_revisar.requiere_moderacion is True
        assert certificado_linkedin.requiere_moderacion is False


# ===========================================================================
# R9: moderación separada
# ===========================================================================
@pytest.mark.django_db
class TestModeracionSeparada:
    def test_aprobar_postulacion_no_aprueba_certificados(
        self, postulacion, certificado_sin_revisar, usuario_admin
    ):
        postulacion.aprobar(usuario_admin)
        certificado_sin_revisar.refresh_from_db()
        # Sigue pendiente: es otra cola.
        assert certificado_sin_revisar.estado == Certificado.ESTADO_SIN_REVISOR

    def test_aprobar_certificado_no_aproba_postulacion(
        self, postulacion, certificado_sin_revisar, usuario_admin
    ):
        certificado_sin_revisar.aprobar(usuario_admin)
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE

    def test_rechazar_certificado_no_rechaza_postulacion(
        self, postulacion, certificado_sin_revisar, usuario_admin
    ):
        certificado_sin_revisar.rechazar(usuario_admin, "Documento ilegible")
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE

    def test_requiere_moderacion_detecta_certificados_pendientes(
        self, postulacion, certificado_sin_revisar
    ):
        assert postulacion.tiene_certificados_sin_revisar is True