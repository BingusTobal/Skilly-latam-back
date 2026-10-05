"""
Permisos y manejo de errores. Ticket 0.13.

Un solo archivo central para que las reglas de acceso sean consistentes en
todas las apps. Regla de AGENTS.md: el permiso se aplica explicito en la vista,
no solo en el serializer.
"""
from django.core.exceptions import ValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class EsAdmin(BasePermission):
    """Solo el administrador de la plataforma (ticket 0.13)."""

    message = "Se requiere permisos de administrador."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(usuario and usuario.is_authenticated and usuario.es_admin_plataforma)


class EsOrganizacion(BasePermission):
    """La cuenta pertenece a una organizacion."""

    message = "Esta operacion es solo para organizaciones."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario
            and usuario.is_authenticated
            and usuario.tipo == UsuarioTipo.ORGANIZACION
        )


class EsProfesional(BasePermission):
    """La cuenta tiene perfil profesional.

    Nota: hasta el Sprint 1 no existe el modelo Profesional, asi que se acepta
    cualquier cuenta marcada como profesional. El ticket 1.2 agrega la
    comprobacion de estado (postulando / aprobado / rechazado / suspendido).
    """

    message = "Esta operacion es solo para profesionales."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario
            and usuario.is_authenticated
            and usuario.tipo == UsuarioTipo.PROFESIONAL
        )


class EsProfesionalAprobado(BasePermission):
    """El profesional tiene estado 'aprobado'. Se activa en el Sprint 1 (1.2)."""

    message = "Tu perfil aun no esta aprobado para publicar."

    def has_permission(self, request, view):
        usuario = request.user
        if not (usuario and usuario.is_authenticated):
            return False
        perfil = getattr(usuario, "profesional", None)
        if perfil is None:
            return False
        return perfil.estado == "aprobado"


class EsPostulante(BasePermission):
    """La cuenta esta en proceso de postulacion o ya fue aprobada."""

    message = "Esta operacion es solo para cuentas postuladas."

    def has_permission(self, request, view):
        usuario = request.user
        if not (usuario and usuario.is_authenticated):
            return False
        if usuario.tipo != UsuarioTipo.PROFESIONAL:
            return False
        perfil = getattr(usuario, "profesional", None)
        if perfil is None:
            return True
        return perfil.estado in ("postulando", "aprobado")


class EsPostulanteOAdmin(BasePermission):
    """Postulante o administrador.

    Necesario donde el endpoint sirve tanto al profesional (su propia
    postulación) como al admin (moderación). DRF exige que PASEN TODOS los
    permisos de la lista, así que `[EsPostulante, EsAdmin]` significaría
    "postulante Y admin", que es justo lo contrario de lo que se quiere.
    """

    message = "Se requiere ser profesional postulante o administrador."

    def has_permission(self, request, view):
        if EsAdmin().has_permission(request, view):
            return True
        return EsPostulante().has_permission(request, view)


class EsPropietarioOAdmin(BasePermission):
    """El objeto pertenece al usuario, salvo que sea admin.

    Se usa en recursos con propietario (servicios, reservas, postulaciones).
    """

    message = "No tienes permiso sobre este recurso."

    def has_object_permission(self, request, view, obj):
        if request.user.is_authenticated and request.user.es_admin_plataforma:
            return True
        propietario = getattr(obj, "profesional", None) or getattr(
            obj, "organizacion", None
        )
        if propietario is None:
            return False
        # El propietario puede ser un modelo o directamente un usuario.
        usuario = getattr(propietario, "usuario", propietario)
        return bool(usuario and usuario.pk == request.user.pk)


class SoloLecturaSiAjeno(BasePermission):
    """Permite leer a todos y escribir solo a quien tiene el rol indicado."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return EsAdmin().has_permission(request, view)


class UsuarioTipo:
    """Evita importar el modelo en los permisos (dependencia circular)."""

    ORGANIZACION = "organizacion"
    PROFESIONAL = "profesional"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Manejo de errores uniforme (referenciado desde REST_FRAMEWORK)
# ---------------------------------------------------------------------------
class ErrorValidacion(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "La solicitud no es valida."
    default_code = "error_validacion"


class ConflictoOperacion(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "La operacion no se puede realizar en el estado actual."
    default_code = "conflicto_operacion"


def exception_handler(exc, context):
    """Normaliza los errores de la API.

    Traduce los errores de Django (incluido el validador de RUT y los `clean()`
    de los modelos) al MISMO formato que usa DRF y simplejwt: `{"detail": ...}`.

    Antes estos errores de Django devolvían `{"error": ...}` y los de DRF
    `{"detail": ...}`, así que la misma API respondía con dos claves según de
    dónde saliera el fallo. El frontend tenía que probar las dos. Acá se
    normaliza todo a `detail`, que es además lo que ya emiten `simplejwt` y
    las vistas del Sprint 1.

    Lo que NO se hace es atrapar excepciones desconocidas: se devuelve None y
    DRF las vuelve a lanzar, para que un error de programación reviente en los
    logs en vez de disfrazarse de respuesta.
    """
    if isinstance(exc, ValidationError):
        detalle = getattr(exc, "message_dict", None) or getattr(exc, "messages", [str(exc)])
        return Response({"detail": detalle}, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, Http404):
        return Response(
            {"detail": "Recurso no encontrado."}, status=status.HTTP_404_NOT_FOUND
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            {"detail": str(exc.detail) if hasattr(exc, "detail") else str(exc)},
            status=status.HTTP_403_FORBIDDEN,
        )

    return drf_exception_handler(exc, context)