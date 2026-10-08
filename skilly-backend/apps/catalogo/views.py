# Vistas de catálogo: público, profesional, admin

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.usuarios.permisos import EsAdmin, EsProfesional

from .models import Categoria, Servicio
from .serializers import (
    CategoriaSerializer,
    ModerarServicioSerializer,
    ServicioAdminSerializer,
    ServicioDetallePublicoSerializer,
    ServicioProfesionalDetalleSerializer,
    ServicioProfesionalSerializer,
    ServicioPublicoSerializer,
)


def _traducir_validacion(exc):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            raise DRFValidationError(exc.message_dict)
        raise DRFValidationError(list(exc.messages))
    raise exc


class CategoriaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Categoria.objects.filter(activa=True).order_by("nombre")
    serializer_class = CategoriaSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ServicioPublicoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Servicio.objects.filter(estado=Servicio.ESTADO_APROBADO, activo=True)
        .select_related("profesional", "categoria")
        .prefetch_related("entregables")
        .order_by("-fecha_publicacion", "-fecha_creacion")
    )
    permission_classes = [AllowAny]
    serializer_class = ServicioPublicoSerializer
    lookup_field = "pk"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ServicioDetallePublicoSerializer
        return ServicioPublicoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        categoria = self.request.query_params.get("categoria")
        if categoria:
            try:
                qs = qs.filter(categoria_id=int(categoria))
            except (TypeError, ValueError):
                qs = qs.filter(Q(categoria__slug=categoria) | Q(categoria__nombre__icontains=categoria))
        formato = self.request.query_params.get("formato")
        if formato:
            qs = qs.filter(formato=formato)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(titulo__icontains=q)
                | Q(descripcion_corta__icontains=q)
                | Q(descripcion_larga__icontains=q)
                | Q(palabras_clave__icontains=q)
                | Q(profesional__nombre_completo__icontains=q)
            )
        return qs


class MisServiciosViewSet(viewsets.ModelViewSet):
    serializer_class = ServicioProfesionalSerializer
    permission_classes = [EsProfesional]
    lookup_field = "pk"

    def get_serializer_class(self):
        if self.action in ("retrieve", "list"):
            return ServicioProfesionalDetalleSerializer
        return ServicioProfesionalSerializer

    def get_queryset(self):
        user = self.request.user
        profesional = getattr(user, "profesional", None)
        if not profesional:
            return Servicio.objects.none()
        qs = Servicio.objects.filter(profesional=profesional).select_related("categoria").prefetch_related("entregables")
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)
        return qs.order_by("-fecha_creacion")

    def _check_publicar_perm(self, request):
        profesional = getattr(request.user, "profesional", None)
        if not profesional or profesional.estado != profesional.ESTADO_APROBADO:
            raise DRFValidationError(
                {"detail": "Solo profesionales aprobados pueden enviar servicios a revisión."}
            )

    @action(detail=True, methods=["post"])
    def publicar(self, request, pk=None):
        servicio = self.get_object()
        self._check_publicar_perm(request)
        try:
            servicio.publicar(request.user)
        except (ValueError, DjangoValidationError) as exc:
            _traducir_validacion(exc)
        return Response(self.get_serializer(servicio).data, status=status.HTTP_200_OK)


class AdminServiciosViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Servicio.objects.all()
        .select_related("profesional", "categoria", "revisado_por")
        .prefetch_related("entregables")
        .order_by("-fecha_creacion")
    )
    serializer_class = ServicioAdminSerializer
    permission_classes = [EsAdmin]
    lookup_field = "pk"

    def get_queryset(self):
        qs = super().get_queryset()
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(titulo__icontains=q)
                | Q(profesional__nombre_completo__icontains=q)
                | Q(profesional__rut__icontains=q)
                | Q(profesional__usuario__email__icontains=q)
                | Q(categoria__nombre__icontains=q)
            )
        return qs

    def _cuerpo_moderacion(self, request, accion):
        serializer = ModerarServicioSerializer(data=request.data, context={"accion": accion})
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data.get("comentarios_admin", "")

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        servicio = self.get_object()
        try:
            servicio.aprobar(request.user)
        except (ValueError, DjangoValidationError) as exc:
            _traducir_validacion(exc)
        return Response(self.get_serializer(servicio).data)

    @action(detail=True, methods=["post"])
    def devolver(self, request, pk=None):
        servicio = self.get_object()
        comentarios = self._cuerpo_moderacion(request, "devolver")
        try:
            servicio.devolver(request.user, comentarios)
        except (ValueError, DjangoValidationError) as exc:
            _traducir_validacion(exc)
        return Response(self.get_serializer(servicio).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        servicio = self.get_object()
        comentarios = self._cuerpo_moderacion(request, "rechazar")
        try:
            servicio.rechazar(request.user, comentarios)
        except (ValueError, DjangoValidationError) as exc:
            _traducir_validacion(exc)
        return Response(self.get_serializer(servicio).data)

    @action(detail=True, methods=["post"])
    def suspender(self, request, pk=None):
        servicio = self.get_object()
        try:
            servicio.suspender(request.user)
        except (ValueError, DjangoValidationError) as exc:
            _traducir_validacion(exc)
        return Response(self.get_serializer(servicio).data)