"""Modelos de la app comisiones.

Ticket 5.4 (RF-30 / R17): la tasa se versiona. Cada cambio crea una fila nueva
con su `vigente_desde`; nunca se sobrescribe una tasa histórica. Los pagos ya
liberados no se recalculan porque `Pago.tasa_aplicada` y
`Reserva.tasa_comision` guardan el snapshot del momento.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TasaComision(models.Model):
    """Tasa de comisión global o por categoría, con historial de versiones.

    `categoria` nula es la tasa global. Una fila por categoría tiene prioridad
    sobre la global para las reservas de esa categoría. La vigente es la fila
    activa con `vigente_desde` más reciente que no supere la fecha consultada.
    """

    categoria = models.ForeignKey(
        "catalogo.Categoria",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasas_comision",
        help_text="Vacío = tasa global. Con categoría, reemplaza a la global.",
    )
    tasa = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("0.9999"))],
        help_text="Fracción entre 0 y 1. Ej: 0.1000 = 10 %.",
    )
    vigente_desde = models.DateField(default=timezone.localdate)
    activa = models.BooleanField(
        default=True,
        help_text="Desactivar permite volver a la versión anterior sin borrar historial.",
    )
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasas_comision_creadas",
    )
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tasa de comisión"
        verbose_name_plural = "tasas de comisión"
        ordering = ["-vigente_desde", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["categoria", "vigente_desde"],
                condition=Q(categoria__isnull=False),
                name="uniq_tasa_comision_categoria_fecha",
            ),
            models.UniqueConstraint(
                fields=["vigente_desde"],
                condition=Q(categoria__isnull=True),
                name="uniq_tasa_comision_global_fecha",
            ),
        ]

    def __str__(self):
        alcance = self.categoria.nombre if self.categoria_id else "Global"
        return f"{alcance}: {self.tasa * 100:g}% desde {self.vigente_desde}"

    def clean(self):
        super().clean()
        if self.tasa is None:
            return
        if self.tasa < 0 or self.tasa >= 1:
            raise ValidationError({"tasa": "La tasa debe ser mayor o igual a 0 y menor que 1."})

    @property
    def porcentaje(self):
        return float(self.tasa) * 100
