"""
Modelos del módulo de pagos (Iteración 4).

`Pago` es el intento de cobro de una reserva; `PagoEvento` es su bitácora
inmutable. Los montos se calculan una sola vez, en CLP enteros, y cumplen
siempre `neto + comisión == total`.
"""
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from . import estados
from .seguridad import sanear, token_corto


class Pago(models.Model):
    """Intento de pago de una reserva.

    Una reserva puede tener varios intentos, pero solo uno vigente. MariaDB no
    soporta índices únicos parciales: la unicidad se garantiza bloqueando la
    fila de la reserva en `pagos.services`.
    """

    PASARELA_FAKE = "fake"
    PASARELA_TRANSBANK = "transbank"
    PASARELA_CHOICES = [
        (PASARELA_FAKE, "Fake"),
        (PASARELA_TRANSBANK, "Transbank"),
    ]

    ACTOR_USUARIO = "usuario"
    ACTOR_PROFESIONAL = "profesional"
    ACTOR_SISTEMA = "sistema"
    ACTOR_ADMIN = "admin"
    ACTOR_CHOICES = [
        (ACTOR_USUARIO, "Usuario"),
        (ACTOR_PROFESIONAL, "Profesional"),
        (ACTOR_SISTEMA, "Sistema"),
        (ACTOR_ADMIN, "Admin"),
    ]

    reserva = models.ForeignKey(
        "reservas.Reserva", on_delete=models.PROTECT, related_name="pagos"
    )
    referencia_publica = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    estado = models.CharField(
        max_length=20,
        choices=estados.ESTADO_CHOICES,
        default=estados.INICIADO,
        db_index=True,
    )
    pasarela = models.CharField(
        max_length=20, choices=PASARELA_CHOICES, default=PASARELA_FAKE
    )

    monto_total = models.PositiveIntegerField()
    monto_comision = models.PositiveIntegerField()
    monto_neto = models.PositiveIntegerField()
    # Snapshot de R17: la tasa con la que se calcularon estos montos. Cambiarla
    # después no recalcula este pago ni los reportes históricos.
    tasa_aplicada = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )

    buy_order = models.CharField(max_length=26, unique=True)
    session_id = models.CharField(max_length=61)
    token = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    url_pago = models.CharField(max_length=255, blank=True)

    codigo_autorizacion = models.CharField(max_length=6, blank=True)
    tipo_pago = models.CharField(max_length=10, blank=True)
    cuotas = models.PositiveSmallIntegerField(default=0)
    tarjeta_ultimos4 = models.CharField(max_length=4, blank=True)
    codigo_respuesta = models.IntegerField(null=True, blank=True)

    # True para débito/prepago: se cobran al confirmar y no admiten captura.
    capturado_en_autorizacion = models.BooleanField(default=False)
    monto_reembolsado = models.PositiveIntegerField(default=0)

    expira_en = models.DateTimeField(null=True, blank=True)
    autorizado_en = models.DateTimeField(null=True, blank=True)
    capturado_en = models.DateTimeField(null=True, blank=True)
    liberado_en = models.DateTimeField(null=True, blank=True)
    reembolsado_en = models.DateTimeField(null=True, blank=True)
    cancelado_en = models.DateTimeField(null=True, blank=True)

    respuesta_pasarela = models.JSONField(default=dict, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["reserva", "estado"]),
        ]

    def __str__(self):
        return f"Pago {self.referencia_publica} — reserva #{self.reserva_id}"

    def save(self, *args, **kwargs):
        if self.tasa_aplicada is None and self.reserva_id:
            self.tasa_aplicada = self.reserva.tasa_comision
        return super().save(*args, **kwargs)

    @property
    def esta_vigente(self):
        return self.estado in estados.ESTADOS_VIGENTES

    @property
    def token_corto(self):
        return token_corto(self.token)

    # Cálculo de montos: total, comisión y neto con un solo redondeo.
    @classmethod
    def calcular_montos(cls, reserva):
        """Calcula los tres montos una sola vez, con redondeo comercial."""
        total = Decimal(reserva.precio_acordado)
        if total != total.to_integral_value():
            raise ValidationError(
                "El monto del servicio debe ser un entero en CLP, sin decimales."
            )
        total = int(total)
        if total <= 0:
            raise ValidationError("El monto del servicio debe ser mayor que cero.")

        tasa = Decimal(str(reserva.tasa_comision))
        if tasa < 0 or tasa > 1:
            raise ValidationError("La tasa de comisión debe estar entre 0 y 1.")

        comision = int(
            (Decimal(total) * tasa).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        return {
            "monto_total": total,
            "monto_comision": comision,
            "monto_neto": total - comision,
        }

    def clean(self):
        super().clean()
        if self.monto_neto + self.monto_comision != self.monto_total:
            raise ValidationError(
                "Los montos del pago no cuadran: neto + comisión debe ser igual al total."
            )
        if self.monto_reembolsado > self.monto_total:
            raise ValidationError(
                "El monto reembolsado no puede superar el total del pago."
            )

    def registrar_evento(self, de_estado, a_estado, actor, motivo="", datos=None):
        return PagoEvento.objects.create(
            pago=self,
            de_estado=de_estado,
            a_estado=a_estado,
            actor=actor,
            motivo=motivo,
            datos=sanear(datos or {}),
        )

    def pasar_a(self, nuevo_estado, *, actor=ACTOR_SISTEMA, motivo="", datos=None):
        """Valida y aplica una transición, dejando un evento inmutable."""
        estados.validar_transicion(self.estado, nuevo_estado)
        anterior = self.estado
        ahora = timezone.now()
        self.estado = nuevo_estado

        campos = ["estado", "actualizado_en"]
        if nuevo_estado == estados.AUTORIZADO:
            self.autorizado_en = ahora
            campos.append("autorizado_en")
        elif nuevo_estado == estados.RETENIDO:
            self.capturado_en = ahora
            campos.append("capturado_en")
        elif nuevo_estado == estados.LIBERADO:
            self.liberado_en = ahora
            campos.append("liberado_en")
        elif nuevo_estado == estados.REEMBOLSADO:
            self.reembolsado_en = ahora
            campos.append("reembolsado_en")
        elif nuevo_estado == estados.CANCELADO:
            self.cancelado_en = ahora
            campos.append("cancelado_en")

        self.save(update_fields=campos)
        return self.registrar_evento(
            anterior, nuevo_estado, actor, motivo=motivo, datos=datos
        )


class PagoEvento(models.Model):
    """Bitácora inmutable de cada transición o llamada relevante."""

    ACTOR_CHOICES = Pago.ACTOR_CHOICES

    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name="eventos")
    de_estado = models.CharField(max_length=20, blank=True)
    a_estado = models.CharField(max_length=20, blank=True)
    motivo = models.TextField(blank=True)
    actor = models.CharField(
        max_length=20, choices=ACTOR_CHOICES, default=Pago.ACTOR_SISTEMA
    )
    datos = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de pago"
        verbose_name_plural = "eventos de pago"
        ordering = ["creado_en", "id"]

    def __str__(self):
        return f"{self.pago_id}: {self.de_estado or 'nuevo'} -> {self.a_estado}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("PagoEvento es inmutable: no se puede modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("PagoEvento es inmutable: no se puede eliminar.")
