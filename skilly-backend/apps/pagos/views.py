"""
Vistas del módulo de pagos.

Endpoints:
- POST /api/reservas/{id}/pago/iniciar/   (dueño JWT o token mágico)
- GET|POST /api/pagos/transbank/retorno/  (pública, exenta de CSRF)
- GET  /api/pagos/{referencia}/estado/    (pública, solo estado)

La vista de retorno nunca confía en el navegador: confirma el token contra la
pasarela antes de cambiar el estado del pago.
"""
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.exceptions import (
    NotAuthenticated,
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reservas.models import Reserva

from . import estados, services
from .models import Pago
from .seguridad import token_corto
from .throttles import EstadoPagoThrottle, IniciarPagoThrottle, RetornoPagoThrottle

logger = logging.getLogger(__name__)

ESTADOS_PUBLICOS_OK = {
    estados.AUTORIZADO,
    estados.CAPTURANDO,
    estados.RETENIDO,
    estados.LIBERADO,
}


def _traducir(exc):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            raise DRFValidationError(exc.message_dict)
        raise DRFValidationError(list(exc.messages))
    raise exc


def _autorizar_reserva(request, reserva):
    """Permite al dueño autenticado o al portador de un token mágico válido."""
    token = request.query_params.get("token") or request.data.get("token")
    if token:
        if reserva.token_valido(token):
            return
        if not request.user.is_authenticated:
            raise PermissionDenied("El enlace de la reserva no es válido o expiró.")

    if not request.user.is_authenticated:
        raise NotAuthenticated("Necesitas iniciar sesión o usar el enlace de acceso.")

    usuario = request.user
    if usuario.es_admin_plataforma:
        return
    if reserva.creada_por_id == usuario.id:
        return
    organizacion = getattr(usuario, "organizacion", None)
    if organizacion is not None and reserva.organizacion_id == organizacion.pk:
        return
    raise PermissionDenied("Esta reserva no te pertenece.")


def _url_resultado(referencia, estado):
    """Arma la URL del frontend sin token, buy_order ni montos."""
    partes = urlsplit(settings.FRONTEND_PAYMENT_RESULT_URL)
    consulta = dict(parse_qsl(partes.query))
    if referencia is not None:
        consulta["ref"] = str(referencia)
    consulta["estado"] = estado
    return urlunsplit(
        (partes.scheme, partes.netloc, partes.path, urlencode(consulta), partes.fragment)
    )


def _estado_publico(pago):
    if pago is None:
        return "fallo"
    return "ok" if pago.estado in ESTADOS_PUBLICOS_OK else "fallo"


class IniciarPagoView(APIView):
    """POST /api/reservas/{id}/pago/iniciar/ (spec 6.2)."""

    permission_classes = [AllowAny]
    throttle_classes = [IniciarPagoThrottle]

    def post(self, request, pk):
        reserva = get_object_or_404(
            Reserva.objects.select_related("servicio", "profesional"), pk=pk
        )
        _autorizar_reserva(request, reserva)

        try:
            inicio = services.iniciar_pago(reserva)
        except (DjangoValidationError, ValueError) as exc:
            _traducir(exc)

        return Response(
            {
                "url": inicio.url,
                "token": inicio.token,
                "referencia_publica": str(inicio.pago.referencia_publica),
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name="dispatch")
class RetornoPagoView(APIView):
    """GET|POST /api/pagos/transbank/retorno/ (spec 6.3)."""

    permission_classes = [AllowAny]
    throttle_classes = [RetornoPagoThrottle]

    def _datos(self, request):
        datos = request.query_params.dict()
        if request.method == "POST":
            datos.update(dict(request.data.items()))
        return datos

    def get(self, request):
        return self._procesar(request)

    def post(self, request):
        return self._procesar(request)

    def _procesar(self, request):
        datos = self._datos(request)
        token_ws = datos.get("token_ws") or ""
        tbk_token = datos.get("TBK_TOKEN") or ""

        if token_ws:
            logger.info("Retorno Webpay para token %s.", token_corto(token_ws))
            try:
                pago = services.confirmar_pago(token_ws)
            except (DjangoValidationError, ValueError):
                logger.warning("Retorno con token desconocido %s.", token_corto(token_ws))
                return redirect(_url_resultado(None, "fallo"))
            except Exception:
                logger.exception("Error inesperado al confirmar el pago.")
                return redirect(_url_resultado(None, "fallo"))
            return redirect(_url_resultado(pago.referencia_publica, _estado_publico(pago)))

        if tbk_token:
            logger.info("Abandono Webpay para token %s.", token_corto(tbk_token))
            try:
                pago = services.abandonar_pago(tbk_token)
            except Exception:
                logger.exception("Error inesperado al registrar el abandono.")
                return redirect(_url_resultado(None, "abandono"))
            if pago is not None and pago.estado != estados.RECHAZADO:
                return redirect(
                    _url_resultado(pago.referencia_publica, _estado_publico(pago))
                )
            referencia = pago.referencia_publica if pago is not None else None
            return redirect(_url_resultado(referencia, "abandono"))

        logger.warning("Retorno Webpay sin token: no se puede identificar el pago.")
        return redirect(_url_resultado(None, "fallo"))


class EstadoPagoView(APIView):
    """GET /api/pagos/{referencia}/estado/ (consulta pública por UUID)."""

    permission_classes = [AllowAny]
    throttle_classes = [EstadoPagoThrottle]

    def get(self, request, referencia):
        pago = get_object_or_404(
            Pago.objects.select_related("reserva"), referencia_publica=referencia
        )
        return Response(
            {
                "referencia_publica": str(pago.referencia_publica),
                "estado": pago.estado,
                "reserva_estado": pago.reserva.estado,
            }
        )
