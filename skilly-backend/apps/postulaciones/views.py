"""
Vistas de postulaciones. Tickets 1.8, 1.11, 1.13.

R9: la moderación de la postulación y la de los certificados son rutas
distintas y estados distintos. `/admin/postulaciones/{id}/aprobar` no toca los
certificados, y `/admin/certificados/{id}/aprobar` no toca la postulación.
"""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.usuarios.correo import (
    enviar_certificado_rechazado,
    enviar_postulacion_aprobada,
    enviar_postulacion_devuelta,
    enviar_postulacion_recibida,
    enviar_postulacion_rechazada,
)
from apps.usuarios.permisos import EsAdmin, EsPostulante, EsPostulanteOAdmin

from .models import Certificado, Postulacion
from .serializers import (
    CertificadoSerializer,
    CrearPostulacionSerializer,
    ModerarCertificadoSerializer,
    ModerarPostulacionSerializer,
    PostulacionAdminSerializer,
    PostulacionSerializer,
)

logger = logging.getLogger(__name__)


def obtener_postulacion_ajena(request, pk):
    """Devuelve la postulación si el usuario tiene derecho a verla; 404 si no.

    Se responde 404 y no 403 a propósito: un profesional no debe poder
    distinguir "no existe" de "existe pero es de otro".
    """
    postulacion = (
        Postulacion.objects.select_related("profesional", "profesional__usuario")
        .filter(pk=pk)
        .first()
    )
    if postulacion is None:
        raise NotFound("Postulación no encontrada.")

    if request.user.es_admin_plataforma:
        return postulacion

    profesional = getattr(request.user, "profesional", None)
    if profesional is None or postulacion.profesional_id != profesional.pk:
        raise NotFound("Postulación no encontrada.")

    return postulacion


class CrearPostulacionView(APIView):
    """POST /api/postulaciones/

    Público y en un solo paso (decisión 1 del Sprint 1): crea Usuario +
    Profesional + Postulacion. No exige sesión ni token mágico.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = CrearPostulacionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        creado = serializer.save()

        postulacion = creado["postulacion"]

        # Acuse de recibo. Si el correo falla, la postulación YA está guardada:
        # un correo que no sale no puede hacer fallar el endpoint.
        enviar_postulacion_recibida(postulacion)

        datos = PostulacionSerializer(postulacion, context={"request": request}).data
        return Response(datos, status=status.HTTP_201_CREATED)


class MiPostulacionView(APIView):
    """GET /api/postulaciones/mias/ — el profesional ve su trámite."""

    permission_classes = [EsPostulante]

    def get(self, request):
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise NotFound("Tu cuenta no tiene perfil profesional.")

        postulacion = (
            Postulacion.objects.filter(profesional=profesional)
            .prefetch_related("certificados")
            .order_by("-fecha_postulacion")
            .first()
        )
        if postulacion is None:
            raise NotFound("Todavía no te has postulado.")

        return Response(
            PostulacionSerializer(postulacion, context={"request": request}).data
        )


class ReenviarPostulacionView(APIView):
    """POST /api/postulaciones/{id}/reenviar/

    El profesional reenvía una postulación que el admin le devolvió.
    """

    permission_classes = [EsPostulante]

    def post(self, request, pk):
        postulacion = obtener_postulacion_ajena(request, pk)

        try:
            postulacion.reenviar(request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PostulacionSerializer(postulacion).data)


class CertificadosPostulacionView(APIView):
    """GET/POST /api/postulaciones/{id}/certificados/

    El POST sube un documento que nace `sin_reviewer`. El admin lo modera
    aparte. Si lo que se sube es la URL de LinkedIn, nace `verificado_automatico`.
    """

    permission_classes = [EsPostulanteOAdmin]

    def get(self, request, pk):
        postulacion = obtener_postulacion_ajena(request, pk)
        return Response(
            CertificadoSerializer(postulacion.certificados.all(), many=True).data
        )

    def post(self, request, pk):
        postulacion = obtener_postulacion_ajena(request, pk)

        serializer = CertificadoSerializer(
            data=request.data, context={"request": request, "postulacion": postulacion}
        )
        serializer.is_valid(raise_exception=True)
        certificado = serializer.save()

        return Response(
            CertificadoSerializer(certificado).data, status=status.HTTP_201_CREATED
        )


# ===========================================================================
# Panel de administración
# ===========================================================================
def _traducir_validacion(exc, status_http=status.HTTP_400_BAD_REQUEST):
    """Convierte una ValidationError de Django en una respuesta DRF."""
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            raise DRFValidationError(exc.message_dict)
        raise DRFValidationError(list(exc.messages))
    raise exc


class AdminPostulacionViewSet(viewsets.ReadOnlyModelViewSet):
    """Cola de moderación de postulaciones. Ticket 1.11.

    Solo lectura en la lista: las transiciones de estado van por las acciones
    explícitas aprobar / rechazar / devolver. Si el estado se pudiera cambiar
    con un PUT libre, se podría saltear el contrato "devolver y rechazar exigen
    comentarios".
    """

    permission_classes = [EsAdmin]
    serializer_class = PostulacionAdminSerializer
    queryset = Postulacion.objects.select_related(
        "profesional", "profesional__usuario", "revisada_por"
    ).prefetch_related("certificados")

    def get_queryset(self):
        qs = super().get_queryset()
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)

        busqueda = (self.request.query_params.get("q") or "").strip()
        if busqueda:
            # El RUT se guarda sin puntos ni guiones, así que una búsqueda
            # escrita "23.181.746-0" tiene que normalizarse antes de comparar.
            rut_busqueda = busqueda.replace(".", "").replace("-", "").replace(" ", "")
            qs = qs.filter(
                Q(profesional__nombre_completo__icontains=busqueda)
                | Q(profesional__rut__icontains=rut_busqueda)
                | Q(profesional__usuario__email__icontains=busqueda)
            )
        return qs

    def _postulacion(self, pk):
        postulacion = self.get_queryset().filter(pk=pk).first()
        if postulacion is None:
            raise NotFound("Postulación no encontrada.")
        return postulacion

    def _cuerpo_moderacion(self, request, accion):
        serializer = ModerarPostulacionSerializer(
            data=request.data, context={"accion": accion}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data.get("comentarios_admin", "")

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        postulacion = self._postulacion(pk)

        if postulacion.estado == Postulacion.ESTADO_APROBADA:
            return Response(
                {"detail": "La postulación ya está aprobada."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            postulacion.aprobar(request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as exc:
            _traducir_validacion(exc)

        # Este correo NO menciona los certificados (R9): los documentos siguen
        # su propia cola de moderación.
        enviar_postulacion_aprobada(postulacion)

        return Response(self.get_serializer(postulacion).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        postulacion = self._postulacion(pk)
        comentarios = self._cuerpo_moderacion(request, "rechazar")

        try:
            postulacion.rechazar(request.user, comentarios)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as exc:
            _traducir_validacion(exc)

        # Ticket 1.12: primer uso real del correo de rechazo.
        enviar_postulacion_rechazada(postulacion)

        return Response(self.get_serializer(postulacion).data)

    @action(detail=True, methods=["post"])
    def devolver(self, request, pk=None):
        postulacion = self._postulacion(pk)
        comentarios = self._cuerpo_moderacion(request, "devolver")

        try:
            postulacion.devolver(request.user, comentarios)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as exc:
            _traducir_validacion(exc)

        enviar_postulacion_devuelta(postulacion)

        return Response(self.get_serializer(postulacion).data)


class AdminCertificadoViewSet(viewsets.ReadOnlyModelViewSet):
    """Cola de moderación de CERTIFICADOS. Ticket 1.11.

    Deliberadamente separada de la de postulaciones (R9). Aprobar un
    certificado NO habilita al profesional a publicar: eso lo decide la
    postulación.
    """

    permission_classes = [EsAdmin]
    serializer_class = CertificadoSerializer
    queryset = Certificado.objects.select_related(
        "postulacion", "postulacion__profesional", "postulacion__profesional__usuario"
    )

    def get_queryset(self):
        qs = super().get_queryset()
        estado = self.request.query_params.get("estado")
        if estado:
            return qs.filter(estado=estado)
        # Sin filtro, la cola son los documentos sin revisar. El perfil de
        # LinkedIn verificado no aparece porque no requiere moderación.
        return qs.filter(estado=Certificado.ESTADO_SIN_REVISOR)

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        certificado = self._certificado(pk)

        try:
            certificado.aprobar(request.user)
        except DjangoValidationError as exc:
            _traducir_validacion(exc)

        return Response(CertificadoSerializer(certificado).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        certificado = self._certificado(pk)

        serializer = ModerarCertificadoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            certificado.rechazar(
                request.user, serializer.validated_data.get("comentario_revisor", "")
            )
        except DjangoValidationError as exc:
            _traducir_validacion(exc)

        enviar_certificado_rechazado(certificado)

        return Response(CertificadoSerializer(certificado).data)

    def _certificado(self, pk):
        certificado = self.get_queryset().filter(pk=pk).first()
        if certificado is None:
            raise NotFound("Certificado no encontrado.")
        return certificado