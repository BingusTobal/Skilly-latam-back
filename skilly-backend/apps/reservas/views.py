"""
Vistas de reservas (tickets 3.1 a 3.6).

Endpoints:
- GET  /api/servicios/{id}/slots/?fecha=YYYY-MM-DD
- GET  /api/servicios/{id}/disponibilidad/?desde=YYYY-MM-DD&dias=45
- POST /api/reservas/                         (con o sin cuenta)
- GET  /api/reservas/mias/                    (organización)
- GET  /api/reservas/solicitudes/             (profesional)
- GET  /api/reservas/{id}/[?token=...]        (dueño, admin o token mágico)
- POST /api/reservas/{id}/aceptar|rechazar|marcar-entregado|confirmar-entrega|cancelar|reportar-problema/
"""
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalogo.models import Servicio

from . import services
from .models import Reserva
from .serializers import (
    AccionReservaSerializer,
    CrearReservaSerializer,
    ReservaOrganizacionSerializer,
    ReservaProfesionalSerializer,
)

SERVICIOS_RESERVABLES = Servicio.objects.filter(
    estado=Servicio.ESTADO_APROBADO, activo=True
)


def _traducir(exc):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            raise DRFValidationError(exc.message_dict)
        raise DRFValidationError(list(exc.messages))
    raise exc


def _fecha(valor):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise DRFValidationError({"fecha": "Usa el formato YYYY-MM-DD."})


class ServicioSlotsView(APIView):
    """GET /api/servicios/{id}/slots/?fecha=YYYY-MM-DD (ticket 3.1)."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        servicio = get_object_or_404(SERVICIOS_RESERVABLES, pk=pk)
        fecha = _fecha(request.query_params.get("fecha"))
        slots = services.calcular_slots(servicio, fecha)
        return Response(
            {
                "fecha": fecha,
                "slot_minutos": settings.SLOT_MINUTOS,
                "bloqueo_horas": settings.HORAS_BLOQUEO_RESERVA,
                "slots": [
                    {
                        "hora_inicio": s["hora_inicio"].strftime("%H:%M"),
                        "hora_fin": s["hora_fin"].strftime("%H:%M"),
                        "disponible": s["disponible"],
                    }
                    for s in slots
                ],
            }
        )


class ServicioDisponibilidadView(APIView):
    """GET /api/servicios/{id}/disponibilidad/?desde=&dias= (calendario)."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        servicio = get_object_or_404(SERVICIOS_RESERVABLES, pk=pk)
        desde = request.query_params.get("desde") or date.today().isoformat()
        fecha = _fecha(desde)
        try:
            dias = min(max(int(request.query_params.get("dias", 45)), 1), 120)
        except (TypeError, ValueError):
            dias = 45
        resumen = services.dias_disponibles(servicio, fecha, dias)
        return Response(
            {
                "desde": fecha,
                "dias": [
                    {"fecha": d["fecha"], "libres": d["libres"]} for d in resumen
                ],
            }
        )


class ReservaViewSet(viewsets.GenericViewSet):
    queryset = Reserva.objects.select_related(
        "servicio", "profesional", "organizacion", "creada_por"
    )
    permission_classes = [AllowAny]

    # ------------------------------------------------------------------ util
    def _exigir_sesion(self):
        if not self.request.user.is_authenticated:
            raise NotAuthenticated("Necesitas iniciar sesión.")

    def _serializer_para(self, reserva, request):
        usuario = request.user
        if usuario.is_authenticated:
            profesional = getattr(usuario, "profesional", None)
            if profesional is not None and reserva.profesional_id == profesional.pk:
                return ReservaProfesionalSerializer(reserva)
        return ReservaOrganizacionSerializer(reserva)

    def _reserva_de(self, request, pk, rol):
        reserva = get_object_or_404(self.get_queryset(), pk=pk)
        if rol == "profesional":
            perfil = getattr(request.user, "profesional", None)
            if perfil is None or reserva.profesional_id != perfil.pk:
                raise PermissionDenied("Esta solicitud no te pertenece.")
        else:
            perfil = getattr(request.user, "organizacion", None)
            if perfil is None or reserva.organizacion_id != perfil.pk:
                raise PermissionDenied("Esta reserva no te pertenece.")
        return reserva

    # --------------------------------------------------------------- lectura
    def create(self, request):
        serializer = CrearReservaSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        creada_por = request.user if request.user.is_authenticated else None
        organizacion = None
        if creada_por is not None:
            organizacion = getattr(creada_por, "organizacion", None)

        datos = {
            clave: data.get(clave, "")
            for clave in ("nombre", "email", "telefono", "empresa", "rut", "mensaje")
        }
        try:
            reserva, token = services.crear_reserva(
                servicio=data["servicio"],
                fecha=data["fecha"],
                hora_inicio=data["hora_inicio"],
                datos=datos,
                organizacion=organizacion,
                creada_por=creada_por,
            )
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)

        salida = self._serializer_para(reserva, request).data
        if token:
            salida["token"] = token
            salida["acceso_url"] = (
                f"{settings.FRONTEND_URL}/reserva/{reserva.pk}?token={token}"
            )
        return Response(salida, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        token = request.query_params.get("token")
        if token:
            reserva = services.buscar_por_token(token)
            if reserva is None or str(reserva.pk) != str(pk):
                raise NotFound("El enlace de la reserva no es válido o expiró.")
            return Response(ReservaOrganizacionSerializer(reserva).data)

        self._exigir_sesion()
        reserva = get_object_or_404(self.get_queryset(), pk=pk)
        usuario = request.user
        es_parte = (
            getattr(usuario, "organizacion", None) == reserva.organizacion
            or getattr(usuario, "profesional", None) == reserva.profesional
        )
        if not es_parte and not usuario.es_admin_plataforma:
            raise PermissionDenied("No tienes permiso sobre esta reserva.")
        return Response(self._serializer_para(reserva, request).data)

    @action(detail=False, methods=["get"])
    def mias(self, request):
        self._exigir_sesion()
        organizacion = getattr(request.user, "organizacion", None)
        if organizacion is None:
            raise PermissionDenied("Esta operación es solo para organizaciones.")
        qs = self.get_queryset().filter(organizacion=organizacion).order_by("-creada_en")
        pagina = self.paginate_queryset(qs)
        serializer = ReservaOrganizacionSerializer(pagina or qs, many=True)
        if pagina is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def solicitudes(self, request):
        self._exigir_sesion()
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise PermissionDenied("Esta operación es solo para profesionales.")
        qs = self.get_queryset().filter(profesional=profesional).order_by("-creada_en")
        estado = request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)
        pagina = self.paginate_queryset(qs)
        serializer = ReservaProfesionalSerializer(pagina or qs, many=True)
        if pagina is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # --------------------------------------------------------------- acciones
    @action(detail=True, methods=["post"])
    def aceptar(self, request, pk=None):
        self._exigir_sesion()
        reserva = self._reserva_de(request, pk, "profesional")
        try:
            services.aceptar(reserva, request.user)
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)
        return Response(ReservaProfesionalSerializer(reserva).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        self._exigir_sesion()
        reserva = self._reserva_de(request, pk, "profesional")
        cuerpo = AccionReservaSerializer(data=request.data)
        cuerpo.is_valid(raise_exception=True)
        try:
            services.rechazar(reserva, request.user, cuerpo.validated_data.get("motivo", ""))
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)
        return Response(ReservaProfesionalSerializer(reserva).data)

    @action(detail=True, methods=["post"], url_path="marcar-entregado")
    def marcar_entregado(self, request, pk=None):
        self._exigir_sesion()
        reserva = self._reserva_de(request, pk, "profesional")
        try:
            services.marcar_entregado(reserva, request.user)
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)
        return Response(ReservaProfesionalSerializer(reserva).data)

    @action(detail=True, methods=["post"], url_path="confirmar-entrega")
    def confirmar_entrega(self, request, pk=None):
        self._exigir_sesion()
        reserva = self._reserva_de(request, pk, "organizacion")
        try:
            services.confirmar_entrega(reserva, request.user)
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)
        return Response(ReservaOrganizacionSerializer(reserva).data)

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        self._exigir_sesion()
        reserva = self._reserva_de(request, pk, "organizacion")
        cuerpo = AccionReservaSerializer(data=request.data)
        cuerpo.is_valid(raise_exception=True)
        try:
            services.cancelar(reserva, request.user, cuerpo.validated_data.get("motivo", ""))
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)
        return Response(ReservaOrganizacionSerializer(reserva).data)

    @action(detail=True, methods=["post"], url_path="reportar-problema")
    def reportar_problema(self, request, pk=None):
        self._exigir_sesion()
        reserva = self._reserva_de(request, pk, "organizacion")
        cuerpo = AccionReservaSerializer(data=request.data)
        cuerpo.is_valid(raise_exception=True)
        try:
            services.reportar_problema(
                reserva,
                request.user,
                cuerpo.validated_data.get("motivo", ""),
                cuerpo.validated_data.get("descripcion", ""),
            )
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)
        return Response(ReservaOrganizacionSerializer(reserva).data)
