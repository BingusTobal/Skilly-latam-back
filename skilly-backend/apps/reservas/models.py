"""
Modelos de la app reservas.

La reserva es el vínculo entre una organización y un profesional: la
organización reserva un servicio publicado, el profesional acepta, ejecuta y
marca la entrega, y la organización confirma. Todo el intercambio de dinero
queda simulado en el MVP (el escrow real es del Sprint 4); acá solo se modela
la relación y su máquina de estados.

Tickets: 3.4 (Reserva), 3.5 (reserva sin cuenta + token mágico),
3.6 (EventoReserva). Disputa se crea como modelo base; su flujo es del Sprint 5.
"""
import hashlib
import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalogo.models import Servicio
from apps.usuarios.models import Organizacion, Profesional


class Reserva(models.Model):
    """Solicitud de reserva de un servicio (ticket 3.4).

    Se guardan "fotografías" (snapshots) del precio y la tasa al momento de
    reservar: si el servicio cambia de precio después, la reserva no se altera.
    """

    ESTADO_PENDIENTE_ACEPTACION = "pendiente_aceptacion"
    ESTADO_EN_CURSO = "en_curso"
    ESTADO_ENTREGADO_POR_CONFIRMAR = "entregado_por_confirmar"
    ESTADO_FINALIZADA = "finalizada"
    ESTADO_CANCELADA = "cancelada"
    ESTADO_VENCIDA = "vencida"
    ESTADO_CON_DISPUTA = "con_disputa"
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE_ACEPTACION, "Pendiente de aceptación"),
        (ESTADO_EN_CURSO, "En curso"),
        (ESTADO_ENTREGADO_POR_CONFIRMAR, "Entregado, por confirmar"),
        (ESTADO_FINALIZADA, "Finalizada"),
        (ESTADO_CANCELADA, "Cancelada"),
        (ESTADO_VENCIDA, "Vencida"),
        (ESTADO_CON_DISPUTA, "Con disputa"),
    ]

    # Estados que ocupan el calendario del profesional: mientras una reserva
    # esté en uno de estos, su ventana (inicio + colchón) está bloqueada.
    ESTADOS_VIGENTES = (
        ESTADO_PENDIENTE_ACEPTACION,
        ESTADO_EN_CURSO,
        ESTADO_ENTREGADO_POR_CONFIRMAR,
        ESTADO_CON_DISPUTA,
    )

    servicio = models.ForeignKey(
        Servicio, on_delete=models.PROTECT, related_name="reservas"
    )
    profesional = models.ForeignKey(
        Profesional, on_delete=models.PROTECT, related_name="reservas"
    )
    organizacion = models.ForeignKey(
        Organizacion, on_delete=models.PROTECT, related_name="reservas"
    )
    # Cuenta que hizo la reserva, si había sesión. NULL en la reserva invitada.
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservas_creadas",
    )

    fecha = models.DateField()
    hora_inicio = models.TimeField()
    # Fin de la ventana bloqueada: hora_inicio + HORAS_BLOQUEO_RESERVA. Se
    # guarda como snapshot para que un cambio de la constante no reinterprete
    # reservas ya creadas.
    hora_fin = models.TimeField()

    # Fotografías del momento de reservar.
    precio_acordado = models.DecimalField(max_digits=10, decimal_places=2)
    tasa_comision = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal(str(getattr(settings, "TASA_COMISION_DEFECTO", 0.10))),
        help_text="Se descuenta del precio para obtener el monto neto del profesional.",
    )
    formato = models.CharField(max_length=20, choices=Servicio.FORMATO_CHOICES)
    ubicacion = models.CharField(max_length=200, blank=True)

    # Datos de contacto de quien reserva. Se copian acá para no depender de la
    # organización (que en la reserva invitada puede no existir todavía).
    contacto_nombre = models.CharField(max_length=200)
    contacto_email = models.EmailField()
    contacto_telefono = models.CharField(max_length=30, blank=True)
    mensaje = models.TextField(
        blank=True,
        help_text="Información adicional para el profesional (INT del formulario).",
    )

    estado = models.CharField(
        max_length=30,
        choices=ESTADO_CHOICES,
        default=ESTADO_PENDIENTE_ACEPTACION,
        db_index=True,
    )

    motivo_rechazo = models.TextField(blank=True)
    motivo_cancelacion = models.TextField(blank=True)
    cancelada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservas_canceladas",
    )

    # Token mágico de la reserva sin cuenta (D7 / ticket 3.5): se guarda solo
    # el hash SHA-256, nunca el token en claro.
    token_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    token_expira = models.DateTimeField(null=True, blank=True)

    # Fecha límite para que el profesional responda (R12, por defecto 6 h).
    expira_en = models.DateTimeField(null=True, blank=True)

    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    aceptada_en = models.DateTimeField(null=True, blank=True)
    entregado_en = models.DateTimeField(null=True, blank=True)
    confirmada_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        ordering = ["-creada_en"]
        indexes = [
            models.Index(fields=["profesional", "fecha"]),
        ]

    def __str__(self):
        return f"Reserva #{self.pk} — {self.servicio.titulo}"

    @property
    def monto_neto(self):
        """Lo que ve el profesional: precio menos la comisión de gestión."""
        return (self.precio_acordado * (Decimal("1") - self.tasa_comision)).quantize(
            Decimal("0.01")
        )

    @property
    def monto_comision(self):
        return (self.precio_acordado - self.monto_neto).quantize(Decimal("0.01"))

    @property
    def esta_vigente(self):
        return self.estado in self.ESTADOS_VIGENTES

    @property
    def expirada(self):
        return bool(self.expira_en and self.expira_en < timezone.now())

    def puede_responder(self):
        return (
            self.estado == self.ESTADO_PENDIENTE_ACEPTACION and not self.expirada
        )

    # --- Token mágico (ticket 3.5) -----------------------------------------
    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def generar_token(self, horas_validez=None):
        """Genera un token de un solo uso y guarda solo su hash."""
        if horas_validez is None:
            horas_validez = getattr(settings, "TOKEN_MAGICO_HORAS", 24)
        token = secrets.token_urlsafe(32)
        self.token_hash = self.hash_token(token)
        self.token_expira = timezone.now() + timezone.timedelta(hours=horas_validez)
        self.save(update_fields=["token_hash", "token_expira"])
        return token

    def token_valido(self, token):
        if not token or not self.token_hash:
            return False
        if not self.token_expira or self.token_expira < timezone.now():
            return False
        return self.hash_token(token) == self.token_hash

    def invalidar_token(self):
        self.token_hash = None
        self.token_expira = None
        self.save(update_fields=["token_hash", "token_expira"])


class EventoReserva(models.Model):
    """Bitácora de la reserva (ticket 3.6).

    Guarda cada hito de la relación: creación, aceptación, rechazo, entrega,
    confirmación, cancelación, vencimiento y reporte de problema. Sirve para
    reconstruir qué pasó sin depender del estado actual.
    """

    TIPO_CREADA = "creada"
    TIPO_ACEPTADA = "aceptada"
    TIPO_RECHAZADA = "rechazada"
    TIPO_ENTREGADA = "entregada"
    TIPO_CONFIRMADA = "confirmada"
    TIPO_CANCELADA = "cancelada"
    TIPO_VENCIDA = "vencida"
    TIPO_PROBLEMA = "problema_reportado"
    TIPO_CHOICES = [
        (TIPO_CREADA, "Creada"),
        (TIPO_ACEPTADA, "Aceptada"),
        (TIPO_RECHAZADA, "Rechazada"),
        (TIPO_ENTREGADA, "Marcada como entregada"),
        (TIPO_CONFIRMADA, "Entrega confirmada"),
        (TIPO_CANCELADA, "Cancelada"),
        (TIPO_VENCIDA, "Vencida"),
        (TIPO_PROBLEMA, "Problema reportado"),
    ]

    reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE, related_name="eventos"
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_reserva",
    )
    detalle = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de reserva"
        verbose_name_plural = "eventos de reserva"
        ordering = ["creado_en", "id"]

    def __str__(self):
        return f"{self.get_tipo_display()} — reserva #{self.reserva_id}"


class Disputa(models.Model):
    """Disputa sobre una reserva. Modelo base (ticket 3.7).

    El flujo completo de moderación de disputas es del Sprint 5; acá solo se
    registra que la organización reportó un problema y pasa la reserva a
    'con_disputa'.
    """

    ESTADO_ABIERTA = "abierta"
    ESTADO_EN_REVISION = "en_revision"
    ESTADO_RESUELTA = "resuelta"
    ESTADO_CHOICES = [
        (ESTADO_ABIERTA, "Abierta"),
        (ESTADO_EN_REVISION, "En revisión"),
        (ESTADO_RESUELTA, "Resuelta"),
    ]

    reserva = models.OneToOneField(
        Reserva, on_delete=models.CASCADE, related_name="disputa"
    )
    motivo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(
        max_length=20, choices=ESTADO_CHOICES, default=ESTADO_ABIERTA
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    resuelta_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "disputa"
        verbose_name_plural = "disputas"
        ordering = ["-creada_en"]

    def __str__(self):
        return f"Disputa reserva #{self.reserva_id} ({self.get_estado_display()})"
