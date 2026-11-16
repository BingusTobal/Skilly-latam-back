"""Resolución de la tasa de comisión vigente (ticket 5.4 / R17)."""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import TasaComision


def _fecha(fecha=None):
    if fecha is None:
        return timezone.localdate()
    if hasattr(fecha, "date"):
        return timezone.localdate(fecha)
    return fecha


def tasa_efectiva_detalle(categoria=None, fecha=None):
    """Devuelve la tasa aplicable y de dónde salió, sin alterar el historial.

    Prioridad: versión de la categoría > versión global > constante de settings.
    """
    dia = _fecha(fecha)
    base = TasaComision.objects.filter(activa=True, vigente_desde__lte=dia)

    if categoria is not None:
        fila = (
            base.filter(categoria=categoria)
            .select_related("categoria")
            .order_by("-vigente_desde", "-id")
            .first()
        )
        if fila:
            return {
                "tasa": fila.tasa,
                "origen": "categoria",
                "vigente_desde": fila.vigente_desde,
                "tasa_id": fila.pk,
                "categoria": fila.categoria,
            }

    fila = (
        base.filter(categoria__isnull=True)
        .order_by("-vigente_desde", "-id")
        .first()
    )
    if fila:
        return {
            "tasa": fila.tasa,
            "origen": "global",
            "vigente_desde": fila.vigente_desde,
            "tasa_id": fila.pk,
            "categoria": None,
        }

    return {
        "tasa": Decimal(str(getattr(settings, "TASA_COMISION_DEFECTO", 0.10))),
        "origen": "defecto",
        "vigente_desde": None,
        "tasa_id": None,
        "categoria": None,
    }


def tasa_efectiva(categoria=None, fecha=None):
    return tasa_efectiva_detalle(categoria=categoria, fecha=fecha)["tasa"]
