"""
Tests de catálogo: modelo Servicio/Entregable y API (público, profesional,
admin).

Cubre el flujo de publicación y revisión de servicios (R9): el profesional
crea el servicio, lo envía a revisión, y el administrador aprueba, devuelve
con comentarios o rechaza.
"""
import pytest
from django.core.exceptions import ValidationError

from apps.catalogo.models import Categoria, Entregable, Servicio
from apps.usuarios.models import Profesional

RUT_PROFESIONAL_VALIDO_2 = "24918073-K"
RUT_OTRO_PROFESIONAL = "16625582-0"


def _crear_otro_profesional(email, rut=RUT_OTRO_PROFESIONAL):
    from django.contrib.auth import get_user_model

    Usuario = get_user_model()
    usuario = Usuario.objects.create_user(email=email, password="AjenoTest123!")
    return Profesional.objects.create(
        usuario=usuario,
        nombre_completo="Profesional Ajeno",
        rut=rut,
        estado=Profesional.ESTADO_APROBADO,
    )


# ===========================================================================
# Modelo: slug automático
# ===========================================================================
@pytest.mark.django_db
class TestSlugServicio:
    def test_genera_slug_desde_el_titulo(self, servicio_borrador):
        assert servicio_borrador.slug == "landing-page-profesional"

    def test_slug_unico_agrega_sufijo(self, profesional_aprobado, categoria):
        primero = Servicio.objects.create(
            profesional=profesional_aprobado,
            categoria=categoria,
            titulo="Servicio repetido",
            precio=1000,
            formato=Servicio.FORMATO_REMOTO,
        )
        segundo = Servicio.objects.create(
            profesional=profesional_aprobado,
            categoria=categoria,
            titulo="Servicio repetido",
            precio=1000,
            formato=Servicio.FORMATO_REMOTO,
        )
        assert primero.slug == "servicio-repetido"
        assert segundo.slug == "servicio-repetido-2"


# ===========================================================================
# Modelo: validaciones de negocio
# ===========================================================================
@pytest.mark.django_db
class TestValidacionesServicio:
    def test_presencial_exige_ubicacion(self, profesional_aprobado, categoria):
        servicio = Servicio(
            profesional=profesional_aprobado,
            categoria=categoria,
            titulo="Masaje",
            precio=10000,
            formato=Servicio.FORMATO_PRESENCIAL,
        )
        with pytest.raises(ValidationError):
            servicio.full_clean()

    def test_precio_negativo_invalido(self, profesional_aprobado, categoria):
        servicio = Servicio(
            profesional=profesional_aprobado,
            categoria=categoria,
            titulo="Curso",
            precio=-1,
            formato=Servicio.FORMATO_REMOTO,
        )
        with pytest.raises(ValidationError):
            servicio.full_clean()

    def test_categoria_no_aprobada_invalida(self, profesional_aprobado):
        categoria = Categoria.objects.create(nombre="Oculta", slug="oculta", aprobada=False)
        servicio = Servicio(
            profesional=profesional_aprobado,
            categoria=categoria,
            titulo="Curso",
            precio=1000,
            formato=Servicio.FORMATO_REMOTO,
        )
        with pytest.raises(ValidationError):
            servicio.full_clean()

    def test_profesional_no_aprobado_no_publica(self, profesional, categoria):
        servicio = Servicio(
            profesional=profesional,
            categoria=categoria,
            titulo="Curso",
            precio=1000,
            formato=Servicio.FORMATO_REMOTO,
            estado=Servicio.ESTADO_EN_REVISION,
        )
        with pytest.raises(ValidationError):
            servicio.full_clean()


# ===========================================================================
# Modelo: máquina de estados
# ===========================================================================
@pytest.mark.django_db
class TestMaquinaEstadosServicio:
    def test_publicar_pasa_a_en_revision(self, servicio_borrador):
        servicio_borrador.publicar()
        servicio_borrador.refresh_from_db()
        assert servicio_borrador.estado == Servicio.ESTADO_EN_REVISION
        assert servicio_borrador.fecha_publicacion is not None

    def test_aprobar_desde_en_revision(self, servicio_en_revision, usuario_admin):
        servicio_en_revision.aprobar(usuario_admin)
        assert servicio_en_revision.estado == Servicio.ESTADO_APROBADO
        assert servicio_en_revision.revisado_por == usuario_admin

    def test_devolver_exige_comentarios(self, servicio_en_revision, usuario_admin):
        with pytest.raises(ValidationError):
            servicio_en_revision.devolver(usuario_admin, "   ")

    def test_devolver_guarda_comentarios(self, servicio_en_revision, usuario_admin):
        servicio_en_revision.devolver(usuario_admin, "Falta portfolio")
        assert servicio_en_revision.estado == Servicio.ESTADO_DEVUELTO
        assert servicio_en_revision.comentarios_admin == "Falta portfolio"

    def test_rechazar_exige_comentarios(self, servicio_en_revision, usuario_admin):
        with pytest.raises(ValidationError):
            servicio_en_revision.rechazar(usuario_admin, "")

    def test_no_aprobar_borrador(self, servicio_borrador, usuario_admin):
        with pytest.raises(ValueError):
            servicio_borrador.aprobar(usuario_admin)

    def test_devuelto_se_puede_republicar(self, servicio_en_revision, usuario_admin):
        servicio_en_revision.devolver(usuario_admin, "Corregir precio")
        servicio_en_revision.publicar()
        assert servicio_en_revision.estado == Servicio.ESTADO_EN_REVISION

    def test_suspender(self, servicio_aprobado, usuario_admin):
        servicio_aprobado.suspender(usuario_admin)
        assert servicio_aprobado.estado == Servicio.ESTADO_SUSPENDIDO


# ===========================================================================
# API pública
# ===========================================================================
@pytest.mark.django_db
class TestApiPublicaServicios:
    url = "/api/servicios/"

    def test_listar_sin_token(self, anon_client, servicio_aprobado):
        respuesta = anon_client.get(self.url)
        assert respuesta.status_code == 200
        assert respuesta.data["count"] == 1

    def test_solo_muestra_aprobados(self, anon_client, servicio_aprobado, servicio_borrador):
        respuesta = anon_client.get(self.url)
        assert respuesta.data["count"] == 1
        assert respuesta.data["results"][0]["slug"] == servicio_aprobado.slug

    def test_filtra_por_categoria(
        self, anon_client, servicio_aprobado, servicio_aprobado_otra_categoria, categoria
    ):
        respuesta = anon_client.get(self.url, {"categoria": categoria.id})
        assert respuesta.data["count"] == 1
        assert respuesta.data["results"][0]["titulo"] == servicio_aprobado.titulo

    def test_busqueda_texto(self, anon_client, servicio_aprobado, servicio_aprobado_otra_categoria):
        respuesta = anon_client.get(self.url, {"q": "Google Ads"})
        assert respuesta.data["count"] == 1

    def test_filtra_por_formato(self, anon_client, servicio_aprobado):
        respuesta = anon_client.get(self.url, {"formato": "remoto"})
        assert respuesta.data["count"] == 1
        respuesta = anon_client.get(self.url, {"formato": "presencial"})
        assert respuesta.data["count"] == 0

    def test_detalle_sugiere_misma_categoria(
        self, anon_client, servicio_aprobado, categoria
    ):
        """Regla del proyecto: se sugieren servicios de la misma categoría,
        no otros profesionales."""
        otro = Servicio.objects.create(
            profesional=servicio_aprobado.profesional,
            categoria=categoria,
            titulo="Otra landing",
            precio=90000,
            formato=Servicio.FORMATO_REMOTO,
            estado=Servicio.ESTADO_APROBADO,
        )
        respuesta = anon_client.get(f"{self.url}{servicio_aprobado.pk}/")
        sugeridos = [s["id"] for s in respuesta.data["sugerencias"]]
        assert otro.id in sugeridos
        assert servicio_aprobado.id not in sugeridos

    def test_detalle_sin_sugerencias_de_otra_categoria(
        self, anon_client, servicio_aprobado, servicio_aprobado_otra_categoria
    ):
        respuesta = anon_client.get(f"{self.url}{servicio_aprobado.pk}/")
        assert respuesta.data["sugerencias"] == []


@pytest.mark.django_db
class TestApiCategorias:
    def test_lista_categorias_activas(self, anon_client, categoria, categoria_otra):
        respuesta = anon_client.get("/api/categorias/")
        assert respuesta.status_code == 200
        assert len(respuesta.data) == 2


# ===========================================================================
# API profesional
# ===========================================================================
@pytest.mark.django_db
class TestApiProfesionalServicios:
    url = "/api/profesional/servicios/"

    def test_requiere_autenticacion(self, anon_client):
        assert anon_client.get(self.url).status_code in (401, 403)

    def test_organizacion_no_accede(self, organizacion_client):
        assert organizacion_client.get(self.url).status_code == 403

    def test_profesional_aprobado_crea_servicio(
        self, profesional_aprobado, profesional_client, categoria
    ):
        payload = {
            "titulo": "Servicio nuevo",
            "descripcion_corta": "corta",
            "descripcion_larga": "larga",
            "precio": 50000,
            "formato": "remoto",
            "categoria": categoria.id,
        }
        respuesta = profesional_client.post(self.url, payload, format="json")
        assert respuesta.status_code == 201
        assert Servicio.objects.count() == 1

    def test_profesional_no_aprobado_no_crea(
        self, profesional, profesional_client, categoria
    ):
        payload = {
            "titulo": "Servicio nuevo",
            "precio": 50000,
            "formato": "remoto",
            "categoria": categoria.id,
        }
        respuesta = profesional_client.post(self.url, payload, format="json")
        assert respuesta.status_code == 400

    def test_solo_ve_sus_servicios(
        self, profesional_aprobado, profesional_client, servicio_borrador, categoria
    ):
        otro = _crear_otro_profesional("ajeno@test.skilly")
        Servicio.objects.create(
            profesional=otro,
            categoria=categoria,
            titulo="De otro",
            precio=1000,
            formato=Servicio.FORMATO_REMOTO,
        )
        respuesta = profesional_client.get(self.url)
        assert respuesta.data["count"] == 1

    def test_publicar_envia_a_revision(
        self, profesional_aprobado, profesional_client, servicio_borrador
    ):
        respuesta = profesional_client.post(f"{self.url}{servicio_borrador.pk}/publicar/")
        assert respuesta.status_code == 200
        servicio_borrador.refresh_from_db()
        assert servicio_borrador.estado == Servicio.ESTADO_EN_REVISION

    def test_actualiza_servicio(
        self, profesional_aprobado, profesional_client, servicio_borrador
    ):
        respuesta = profesional_client.patch(
            f"{self.url}{servicio_borrador.pk}/", {"precio": 99900}, format="json"
        )
        assert respuesta.status_code == 200
        servicio_borrador.refresh_from_db()
        assert servicio_borrador.precio == 99900

    def test_actualiza_entregables(
        self, profesional_aprobado, profesional_client, servicio_borrador
    ):
        respuesta = profesional_client.patch(
            f"{self.url}{servicio_borrador.pk}/",
            {"entregables": [{"nombre": "Solo uno"}]},
            format="json",
        )
        assert respuesta.status_code == 200
        assert servicio_borrador.entregables.count() == 1

    def test_publicar_sin_estar_aprobado(
        self, profesional_aprobado, profesional_client, servicio_borrador
    ):
        profesional_aprobado.estado = Profesional.ESTADO_POSTULANDO
        profesional_aprobado.save()
        respuesta = profesional_client.post(f"{self.url}{servicio_borrador.pk}/publicar/")
        assert respuesta.status_code == 400

    def test_no_publicar_ajeno(
        self, profesional_aprobado, profesional_client, categoria
    ):
        otro = _crear_otro_profesional("ajeno2@test.skilly")
        ajeno = Servicio.objects.create(
            profesional=otro,
            categoria=categoria,
            titulo="Ajeno",
            precio=1000,
            formato=Servicio.FORMATO_REMOTO,
        )
        respuesta = profesional_client.post(f"{self.url}{ajeno.pk}/publicar/")
        assert respuesta.status_code == 404


# ===========================================================================
# API admin: cola de revisión
# ===========================================================================
@pytest.mark.django_db
class TestApiAdminServicios:
    url = "/api/admin/servicios/"

    def test_requiere_admin(self, anon_client, profesional_client):
        assert anon_client.get(self.url).status_code in (401, 403)
        assert profesional_client.get(self.url).status_code == 403

    def test_admin_lista_todos(self, admin_client, servicio_borrador, servicio_aprobado):
        respuesta = admin_client.get(self.url)
        assert respuesta.data["count"] == 2

    def test_admin_filtra_por_estado(self, admin_client, servicio_borrador, servicio_aprobado):
        respuesta = admin_client.get(self.url, {"estado": "aprobado"})
        assert respuesta.data["count"] == 1

    def test_aprobar(self, admin_client, servicio_en_revision):
        respuesta = admin_client.post(f"{self.url}{servicio_en_revision.pk}/aprobar/")
        assert respuesta.status_code == 200
        servicio_en_revision.refresh_from_db()
        assert servicio_en_revision.estado == Servicio.ESTADO_APROBADO

    def test_devolver_sin_comentarios_da_400(self, admin_client, servicio_en_revision):
        respuesta = admin_client.post(
            f"{self.url}{servicio_en_revision.pk}/devolver/", {}, format="json"
        )
        assert respuesta.status_code == 400

    def test_devolver_con_comentarios(self, admin_client, servicio_en_revision):
        respuesta = admin_client.post(
            f"{self.url}{servicio_en_revision.pk}/devolver/",
            {"comentarios_admin": "Falta precio"},
            format="json",
        )
        assert respuesta.status_code == 200
        servicio_en_revision.refresh_from_db()
        assert servicio_en_revision.estado == Servicio.ESTADO_DEVUELTO

    def test_rechazar(self, admin_client, servicio_en_revision):
        respuesta = admin_client.post(
            f"{self.url}{servicio_en_revision.pk}/rechazar/",
            {"comentarios_admin": "No cumple políticas"},
            format="json",
        )
        assert respuesta.status_code == 200

    def test_suspender(self, admin_client, servicio_aprobado):
        respuesta = admin_client.post(f"{self.url}{servicio_aprobado.pk}/suspender/")
        assert respuesta.status_code == 200
        servicio_aprobado.refresh_from_db()
        assert servicio_aprobado.estado == Servicio.ESTADO_SUSPENDIDO


# ===========================================================================
# Entregables anidados
# ===========================================================================
@pytest.mark.django_db
class TestEntregablesAnidados:
    def test_crea_con_entregables(self, profesional_aprobado, profesional_client, categoria):
        payload = {
            "titulo": "Con entregables",
            "precio": 10000,
            "formato": "remoto",
            "categoria": categoria.id,
            "entregables": [
                {"nombre": "Archivo fuente", "orden": 1},
                {"nombre": "Manual", "orden": 2},
            ],
        }
        respuesta = profesional_client.post(
            "/api/profesional/servicios/", payload, format="json"
        )
        assert respuesta.status_code == 201
        assert Entregable.objects.filter(servicio_id=respuesta.data["id"]).count() == 2