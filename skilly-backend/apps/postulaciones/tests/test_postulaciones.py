"""
Tests de API de postulaciones. Tickets 1.8, 1.11, 1.12.

Cubre los tres momentos del ciclo de vida desde la perspectiva HTTP:
la postulación pública, el reenvío del profesional y las tres acciones de
moderación del admin.
"""
import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.postulaciones.models import Certificado, Postulacion
from apps.usuarios.models import Profesional

RUT_PROF_NUEVO = "24918073-K"


@pytest.fixture
def payload_postulacion():
    return {
        "email": "nuevo.profesional@test.skilly",
        "password": "ProfTest123!",
        "nombre_completo": "Camila Soto",
        "rut": RUT_PROF_NUEVO,
        "telefono": "+56987654321",
        "ciudad": "Valparaíso",
        "linkedin_url": "https://www.linkedin.com/in/camila-soto",
        "disponibilidad": "inmediata",
        "especialidad": "Traducción",
        "experiencia": "8 años traduciendo textos técnicos.",
    }


# ===========================================================================
# Postulación pública (1.8)
# ===========================================================================
@pytest.mark.django_db
class TestCrearPostulacion:
    url = "/api/postulaciones/"

    def test_es_publica_sin_token(self, anon_client, payload_postulacion):
        respuesta = anon_client.post(self.url, payload_postulacion, format="json")
        assert respuesta.status_code == 201

    def test_crea_usuario_profesional_y_postulacion(
        self, anon_client, payload_postulacion
    ):
        from django.contrib.auth import get_user_model

        Usuario = get_user_model()
        anon_client.post(self.url, payload_postulacion, format="json")

        usuario = Usuario.objects.get(email="nuevo.profesional@test.skilly")
        assert usuario.tipo == Usuario.TIPO_PROFESIONAL
        assert usuario.is_active is True

        profesional = Profesional.objects.get(usuario=usuario)
        assert profesional.estado == Profesional.ESTADO_POSTULANDO

        postulacion = Postulacion.objects.get(profesional=profesional)
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE
        assert postulacion.especialidad == "Traducción"

    def test_es_un_solo_paso(self, anon_client, payload_postulacion):
        """Decisión 1: no hay que registrarse antes. Un solo POST deja al
        profesional listo para publicar, pendiente de moderación."""
        respuesta = anon_client.post(self.url, payload_postulacion, format="json")
        assert respuesta.status_code == 201
        assert respuesta.data["estado"] == "pendiente"

    def test_devuelve_la_postulacion_creada(self, anon_client, payload_postulacion):
        respuesta = anon_client.post(self.url, payload_postulacion, format="json")
        assert respuesta.data["profesional_nombre"] == "Camila Soto"
        assert respuesta.data["especialidad"] == "Traducción"

    def test_envia_acuse_de_recibo(self, anon_client, payload_postulacion):
        anon_client.post(self.url, payload_postulacion, format="json")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["nuevo.profesional@test.skilly"]

    def test_crea_el_certificado_de_linkedin_automaticamente(
        self, anon_client, payload_postulacion
    ):
        """Decisión 3: el perfil de LinkedIn se registra como certificado, y
        entra verificado por formato de URL sin pasar por moderación."""
        anon_client.post(self.url, payload_postulacion, format="json")

        postulacion = Postulacion.objects.get()
        linkedin = postulacion.certificados.get(tipo=Certificado.TIPO_LINKEDIN)
        assert linkedin.estado == Certificado.ESTADO_VERIFICADO_AUTOMATICO
        assert linkedin.enlace == "https://www.linkedin.com/in/camila-soto"

    def test_sin_linkedin_no_crea_certificado(
        self, anon_client, payload_postulacion
    ):
        payload_postulacion.pop("linkedin_url")
        anon_client.post(self.url, payload_postulacion, format="json")
        assert Postulacion.objects.get().certificados.count() == 0

    def test_rechaza_certificados_anidados(
        self, anon_client, payload_postulacion
    ):
        """Los documentos no se aceptan en el cuerpo JSON de la postulación: un
        archivo no viaja dentro de JSON. Van por
        `POST /api/postulaciones/{id}/certificados/` una vez que la cuenta
        existe. Que el campo se reporte como desconocido es preferible a que
        parezca funcionar y despierte."""
        payload_postulacion["certificados"] = [{"tipo": "otro", "nombre": "Título"}]
        respuesta = anon_client.post(self.url, payload_postulacion, format="json")
        assert "certificados" in respuesta.data

    def test_el_documento_se_sube_despues_y_queda_en_la_cola(
        self, anon_client, payload_postulacion
    ):
        """El flujo completo: se postula, se hace login y se sube el documento.
        Este nace `sin_reviewer`, nunca verificado."""
        anon_client.post(self.url, payload_postulacion, format="json")

        login = anon_client.post(
            "/api/auth/login/",
            {
                "email": "nuevo.profesional@test.skilly",
                "password": "ProfTest123!",
            },
            format="json",
        )
        assert login.status_code == 200

        postulacion = Postulacion.objects.get()
        respuesta = anon_client.post(
            f"/api/postulaciones/{postulacion.pk}/certificados/",
            {
                "tipo": "otro",
                "nombre": "Título profesional",
                "archivo": SimpleUploadedFile(
                    "titulo.pdf", b"%PDF-1.4 prueba", content_type="application/pdf"
                ),
            },
            format="multipart",
            HTTP_AUTHORIZATION="Bearer " + login.data["access"],
        )
        assert respuesta.status_code == 201

        documento = postulacion.certificados.get(tipo=Certificado.TIPO_OTRO)
        assert documento.estado == Certificado.ESTADO_SIN_REVISOR

    def test_rechaza_rut_invalido(self, anon_client, payload_postulacion):
        respuesta = anon_client.post(
            self.url, {**payload_postulacion, "rut": "76541230-4"}, format="json"
        )
        assert respuesta.status_code == 400
        assert "rut" in respuesta.data

    def test_rechaza_rut_duplicado(self, anon_client, payload_postulacion, profesional):
        respuesta = anon_client.post(
            self.url, {**payload_postulacion, "rut": profesional.rut}, format="json"
        )
        assert respuesta.status_code == 400
        assert "rut" in respuesta.data

    def test_rechaza_correo_ya_registrado(
        self, anon_client, payload_postulacion, usuario_profesional
    ):
        respuesta = anon_client.post(
            self.url,
            {**payload_postulacion, "email": "profesional@test.skilly"},
            format="json",
        )
        assert respuesta.status_code == 400
        assert "email" in respuesta.data

    def test_rechaza_url_de_linkedin_con_otro_formato(
        self, anon_client, payload_postulacion
    ):
        respuesta = anon_client.post(
            self.url,
            {**payload_postulacion, "linkedin_url": "https://facebook.com/camila"},
            format="json",
        )
        assert respuesta.status_code == 400

    def test_rechaza_password_debil(self, anon_client, payload_postulacion):
        respuesta = anon_client.post(
            self.url, {**payload_postulacion, "password": "123"}, format="json"
        )
        assert respuesta.status_code == 400

    def test_no_deja_usuario_a_medio_crear(
        self, anon_client, payload_postulacion
    ):
        """La creación es atómica: si algo falla al final, tampoco queda el
        usuario ni el profesional a medio crear."""
        from django.contrib.auth import get_user_model

        Usuario = get_user_model()

        # linkedin_url no puede ser una URL de LinkedIn y a la vez fallar de
        # otra forma: se rompe con un tipo de disponibilidad inexistente, que
        # se valida DESPUES de haber creado usuario y profesional.
        payload_postulacion["disponibilidad"] = "cuando_se_te_ocurra"
        respuesta = anon_client.post(self.url, payload_postulacion, format="json")
        assert respuesta.status_code == 400

        assert not Usuario.objects.filter(
            email="nuevo.profesional@test.skilly"
        ).exists()
        assert not Postulacion.objects.exists()
        assert not Profesional.objects.filter(
            nombre_completo="Camila Soto"
        ).exists()


# ===========================================================================
# El profesional ve su trámite
# ===========================================================================
@pytest.mark.django_db
class TestMiPostulacion:
    url = "/api/postulaciones/mias/"

    def test_requiere_autenticacion(self, anon_client):
        assert anon_client.get(self.url).status_code == 401

    def test_devuelve_su_postulacion(self, profesional_client, postulacion):
        respuesta = profesional_client.get(self.url)
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "pendiente"

    def test_incluye_sus_certificados(self, profesional_client, certificado_sin_revisar):
        respuesta = profesional_client.get(self.url)
        assert len(respuesta.data["certificados"]) == 1
        assert respuesta.data["tiene_certificados_sin_revisar"] is True

    def test_sin_postulacion_da_404(self, profesional_client, profesional):
        respuesta = profesional_client.get(self.url)
        assert respuesta.status_code == 404

    def test_ve_los_comentarios_del_admin(
        self, profesional_client, postulacion, usuario_admin
    ):
        postulacion.devolver(usuario_admin, "Indica el número de años.")
        respuesta = profesional_client.get(self.url)
        assert respuesta.data["estado"] == "devuelta"
        assert respuesta.data["comentarios_admin"] == "Indica el número de años."


# ===========================================================================
# Reenvío (1.10)
# ===========================================================================
@pytest.mark.django_db
class TestReenviarPostulacion:
    def url(self, pk):
        return f"/api/postulaciones/{pk}/reenviar/"

    def test_profesional_reenvia_una_devuelta(
        self, profesional_client, postulacion, usuario_admin
    ):
        postulacion.devolver(usuario_admin, "Falta detalle.")
        respuesta = profesional_client.post(self.url(postulacion.pk))
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "pendiente"

    def test_limpia_los_comentarios_al_reenviar(
        self, profesional_client, postulacion, usuario_admin
    ):
        postulacion.devolver(usuario_admin, "Falta detalle.")
        profesional_client.post(self.url(postulacion.pk))
        postulacion.refresh_from_db()
        assert postulacion.comentarios_admin == ""

    def test_no_se_puede_reenviar_una_pendiente(
        self, profesional_client, postulacion
    ):
        respuesta = profesional_client.post(self.url(postulacion.pk))
        assert respuesta.status_code == 400

    def test_no_puede_reenviar_postulacion_de_otro(
        self, profesional_client, postulacion, profesional_otro, usuario_admin
    ):
        postulacion.profesional = profesional_otro
        postulacion.save()
        postulacion.devolver(usuario_admin, "Corregir.")

        respuesta = profesional_client.post(self.url(postulacion.pk))
        # 404 y no 403: no debe poder distinguir "no existe" de "es de otro".
        assert respuesta.status_code == 404


# ===========================================================================
# Certificados del profesional (1.9)
# ===========================================================================
@pytest.mark.django_db
class TestCertificadosPostulacion:
    def url(self, pk):
        return f"/api/postulaciones/{pk}/certificados/"

    def test_profesional_sube_un_documento(
        self, profesional_client, postulacion
    ):
        respuesta = profesional_client.post(
            self.url(postulacion.pk),
            {
                "tipo": "otro",
                "nombre": "Título profesional",
                "archivo": SimpleUploadedFile(
                    "titulo.pdf", b"%PDF-1.4 prueba", content_type="application/pdf"
                ),
            },
            format="multipart",
        )
        assert respuesta.status_code == 201
        assert respuesta.data["estado"] == "sin_reviewer"

    def test_sube_linkedin_y_nace_verificado(self, profesional_client, postulacion):
        respuesta = profesional_client.post(
            self.url(postulacion.pk),
            {
                "tipo": "linkedin",
                "nombre": "Mi perfil",
                "enlace": "https://www.linkedin.com/in/juan-perez",
            },
            format="multipart",
        )
        assert respuesta.status_code == 201
        assert respuesta.data["estado"] == "verificado_automatico"

    def test_rechaza_archivo_demasiado_grande(self, profesional_client, postulacion):
        grande = SimpleUploadedFile(
            "grande.pdf", b"x" * (6 * 1024 * 1024), content_type="application/pdf"
        )
        respuesta = profesional_client.post(
            self.url(postulacion.pk),
            {"tipo": "otro", "nombre": "Pesado", "archivo": grande},
            format="multipart",
        )
        assert respuesta.status_code == 400

    def test_rechaza_tipo_de_archivo_no_permitido(
        self, profesional_client, postulacion
    ):
        respuesta = profesional_client.post(
            self.url(postulacion.pk),
            {
                "tipo": "otro",
                "nombre": "Ejecutable",
                "archivo": SimpleUploadedFile(
                    "virus.exe", b"MZ", content_type="application/x-msdownload"
                ),
            },
            format="multipart",
        )
        assert respuesta.status_code == 400

    def test_no_puede_subir_a_la_postulacion_de_otro(
        self, profesional_client, postulacion, profesional_otro
    ):
        postulacion.profesional = profesional_otro
        postulacion.save()
        respuesta = profesional_client.post(
            self.url(postulacion.pk),
            {
                "tipo": "otro",
                "nombre": "Intruso",
                "archivo": SimpleUploadedFile(
                    "x.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
            },
            format="multipart",
        )
        assert respuesta.status_code == 404


# ===========================================================================
# Moderación de postulaciones (1.11, 1.12)
# ===========================================================================
@pytest.mark.django_db
class TestModeracionAdmin:
    def url(self, pk):
        return f"/api/postulaciones/admin/postulaciones/{pk}/"

    def resultados(self, respuesta):
        """Las vistas del admin usan paginacion, asi que las listas vienen
        anidadas en `results`."""
        return respuesta.data["results"]

    def test_profesional_no_entra_al_panel(self, profesional_client, postulacion):
        respuesta = profesional_client.post(f"{self.url(postulacion.pk)}aprobar/")
        assert respuesta.status_code == 403

    def test_organizacion_no_entra_al_panel(self, organizacion_client, postulacion):
        respuesta = organizacion_client.get(
            "/api/postulaciones/admin/postulaciones/"
        )
        assert respuesta.status_code == 403

    def test_aprobar(self, admin_client, postulacion, usuario_admin):
        respuesta = admin_client.post(f"{self.url(postulacion.pk)}aprobar/")
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "aprobada"

    def test_aprobar_envia_correo(self, admin_client, postulacion):
        admin_client.post(f"{self.url(postulacion.pk)}aprobar/")
        assert len(mail.outbox) == 1
        assert "aprobada" in mail.outbox[0].subject.lower()

    def test_aprobar_ya_aprobada_da_409(self, admin_client, postulacion):
        admin_client.post(f"{self.url(postulacion.pk)}aprobar/")
        segunda = admin_client.post(f"{self.url(postulacion.pk)}aprobar/")
        assert segunda.status_code == 409

    def test_devolver_exige_comentarios(self, admin_client, postulacion):
        respuesta = admin_client.post(
            f"{self.url(postulacion.pk)}devolver/", {}, format="json"
        )
        assert respuesta.status_code == 400
        assert "comentarios_admin" in respuesta.data

    def test_devolver_con_comentarios(self, admin_client, postulacion):
        respuesta = admin_client.post(
            f"{self.url(postulacion.pk)}devolver/",
            {"comentarios_admin": "Agrega tu portfolio."},
            format="json",
        )
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "devuelta"
        assert respuesta.data["comentarios_admin"] == "Agrega tu portfolio."

    def test_devuelta_envia_correo_con_los_comentarios(self, admin_client, postulacion):
        admin_client.post(
            f"{self.url(postulacion.pk)}devolver/",
            {"comentarios_admin": "Agrega tu portfolio."},
            format="json",
        )
        assert len(mail.outbox) == 1
        assert "portfolio" in mail.outbox[0].body

    def test_rechazar_exige_comentarios(self, admin_client, postulacion):
        respuesta = admin_client.post(
            f"{self.url(postulacion.pk)}rechazar/", {}, format="json"
        )
        assert respuesta.status_code == 400

    def test_rechazar_con_comentarios(self, admin_client, postulacion):
        respuesta = admin_client.post(
            f"{self.url(postulacion.pk)}rechazar/",
            {"comentarios_admin": "No cubrimos tu especialidad."},
            format="json",
        )
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "rechazada"

    def test_registra_who_reviso(self, admin_client, postulacion, usuario_admin):
        admin_client.post(f"{self.url(postulacion.pk)}aprobar/")
        postulacion.refresh_from_db()
        assert postulacion.revisada_por == usuario_admin

    def test_la_lista_permite_filtrar_por_estado(self, admin_client, postulacion):
        todas = admin_client.get("/api/postulaciones/admin/postulaciones/")
        assert len(self.resultados(todas)) == 1

        admin_client.post(f"{self.url(postulacion.pk)}aprobar/")
        pendientes = admin_client.get(
            "/api/postulaciones/admin/postulaciones/", {"estado": "pendiente"}
        )
        assert len(self.resultados(pendientes)) == 0

    def test_devuelve_paginacion(self, admin_client, postulacion):
        """El panel admin lista en paginas: sin esto, la cola creceria sin
        limite en cada request."""
        respuesta = admin_client.get("/api/postulaciones/admin/postulaciones/")
        assert set(respuesta.data) >= {"count", "next", "previous", "results"}

    def test_busca_por_rut_escrito_con_puntos(self, admin_client, postulacion):
        """El RUT se guarda normalizado; la búsqueda written con puntos tiene
        que encontrarlo igual."""
        respuesta = admin_client.get(
            "/api/postulaciones/admin/postulaciones/", {"q": "23.181.746-0"}
        )
        assert len(self.resultados(respuesta)) == 1

    def test_la_lista_es_solo_lectura(self, admin_client, postulacion):
        """Cambiar el estado por PUT saltearía el contrato de comentarios."""
        respuesta = admin_client.patch(
            "/api/postulaciones/admin/postulaciones/",
            {"estado": "aprobada"},
            format="json",
        )
        assert respuesta.status_code == 405


# ===========================================================================
# Moderación de certificados (R9) — cola separada
# ===========================================================================
@pytest.mark.django_db
class TestModeracionCertificados:
    def url_cert(self, pk):
        return f"/api/postulaciones/admin/certificados/{pk}/"

    def url_queue(self):
        return "/api/postulaciones/admin/certificados/"

    def test_la_cola_solo_muestra_lo_que_esta_sin_revisar(
        self, admin_client, certificado_sin_revisar, certificado_linkedin
    ):
        """El perfil de LinkedIn no aparece: no requiere moderación."""
        respuesta = admin_client.get(self.url_queue())
        cola = respuesta.data["results"]
        assert [c["id"] for c in cola] == [certificado_sin_revisar.id]

    def test_aprobar_certificado(self, admin_client, certificado_sin_revisar):
        respuesta = admin_client.post(f"{self.url_cert(certificado_sin_revisar.pk)}aprobar/")
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "aprobado"

    def test_aprobar_certificado_no_aprueba_la_postulacion(
        self, admin_client, postulacion, certificado_sin_revisar
    ):
        admin_client.post(f"{self.url_cert(certificado_sin_revisar.pk)}aprobar/")
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE

    def test_rechazar_certificado_exige_comentario_opcional(
        self, admin_client, certificado_sin_revisar
    ):
        respuesta = admin_client.post(
            f"{self.url_cert(certificado_sin_revisar.pk)}rechazar/",
            {"comentario_revisor": "El PDF está ilegible."},
            format="json",
        )
        assert respuesta.status_code == 200
        assert respuesta.data["estado"] == "rechazado"

    def test_rechazar_certificado_envia_correo(self, admin_client, certificado_sin_revisar):
        admin_client.post(
            f"{self.url_cert(certificado_sin_revisar.pk)}rechazar/",
            {"comentario_revisor": "Ilegible."},
            format="json",
        )
        assert len(mail.outbox) == 1
        # El correo aclara que el documento y la postulación son cosas aparte.
        assert "independiente" in mail.outbox[0].body.lower()

    def test_rechazar_certificado_no_rechaza_la_postulacion(
        self, admin_client, postulacion, certificado_sin_revisar
    ):
        admin_client.post(
            f"{self.url_cert(certificado_sin_revisar.pk)}rechazar/",
            {"comentario_revisor": "Ilegible."},
            format="json",
        )
        postulacion.refresh_from_db()
        assert postulacion.estado == Postulacion.ESTADO_PENDIENTE

    def test_no_se_puede_moderar_linkedin(self, admin_client, certificado_linkedin):
        """Y al no estar en la cola, ni siquiera es alcanzable por id."""
        admin_client.post(f"{self.url_cert(certificado_linkedin.pk)}aprobar/")
        certificado_linkedin.refresh_from_db()
        assert certificado_linkedin.estado == Certificado.ESTADO_VERIFICADO_AUTOMATICO

    def test_profesional_no_moderar_certificados(
        self, profesional_client, certificado_sin_revisar
    ):
        respuesta = profesional_client.post(
            f"{self.url_cert(certificado_sin_revisar.pk)}aprobar/"
        )
        assert respuesta.status_code == 403