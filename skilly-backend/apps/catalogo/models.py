"""
Modelos de la app catalogo.

Ticket 0.15 (sprint actual) adelantado: se crea Categoria porque el comando
cargar_seed lo necesita. Servicio y Entregable son del Sprint 2 (tickets 2.2
y 2.3) y siguen pendientes.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.usuarios.models import Profesional


class Categoria(models.Model):
    """
    Categoria de servicios. Publicar un servicio exige una categoria aprobada
    (ticket 2.1).
    """

    nombre = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    # 0.15: las 5 categorias del seed entran ya aprobadas para que el flujo de
    # publicacion se pueda probar desde el Sprint 1.
    aprobada = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Servicio(models.Model):
    """Servicio publicado por un profesional.

    El profesional crea el servicio (generalmente en borrador). Al publicar
    (`publicar()`) pasa a estado 'en_revision'. Un administrador lo revisa y
    aprueba, devuelve con comentarios o rechaza (R9 de publicación de
    servicios).
    """

    ESTADO_BORRADOR = "borrador"
    ESTADO_EN_REVISION = "en_revision"
    ESTADO_APROBADO = "aprobado"
    ESTADO_RECHAZADO = "rechazado"
    ESTADO_DEVUELTO = "devuelto"
    ESTADO_SUSPENDIDO = "suspendido"
    ESTADO_CHOICES = [
        (ESTADO_BORRADOR, "Borrador"),
        (ESTADO_EN_REVISION, "En revisión"),
        (ESTADO_APROBADO, "Aprobado"),
        (ESTADO_RECHAZADO, "Rechazado"),
        (ESTADO_DEVUELTO, "Devuelto"),
        (ESTADO_SUSPENDIDO, "Suspendido"),
    ]

    FORMATO_REMOTO = "remoto"
    FORMATO_PRESENCIAL = "presencial"
    FORMATO_SEMIPRESENCIAL = "semipresencial"  # Híbrido
    FORMATO_CHOICES = [
        (FORMATO_REMOTO, "Remoto"),
        (FORMATO_PRESENCIAL, "Presencial"),
        (FORMATO_SEMIPRESENCIAL, "Semipresencial (Híbrido)"),
    ]

    profesional = models.ForeignKey(
        Profesional,
        on_delete=models.CASCADE,
        related_name="servicios",
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="servicios",
    )

    titulo = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)

    descripcion_corta = models.CharField(max_length=280, blank=True)
    descripcion_larga = models.TextField(blank=True)

    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Precio fijo del servicio (CLP).",
    )

    formato = models.CharField(max_length=20, choices=FORMATO_CHOICES)
    ubicacion = models.CharField(max_length=200, blank=True)

    duracion_estimada = models.CharField(
        max_length=100,
        blank=True,
        help_text="Ej.: '2 horas', '3-5 días'.",
    )

    palabras_clave = models.CharField(max_length=255, blank=True)

    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default=ESTADO_BORRADOR,
        db_index=True,
    )

    comentarios_admin = models.TextField(
        blank=True,
        help_text="Comentarios del administrador al devolver o rechazar.",
    )

    activo = models.BooleanField(default=True)

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_ultima_actualizacion = models.DateTimeField(auto_now=True)
    fecha_publicacion = models.DateTimeField(null=True, blank=True)
    fecha_revision = models.DateTimeField(null=True, blank=True)
    revisado_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="servicios_revisados",
    )

    class Meta:
        verbose_name = "servicio"
        verbose_name_plural = "servicios"
        ordering = ["-fecha_creacion"]

    def __str__(self):
        return self.titulo

    def _generar_slug(self):
        base = slugify(self.titulo) or "servicio"
        slug = base
        contador = 1
        while Servicio.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            contador += 1
            slug = f"{base}-{contador}"
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generar_slug()
        else:
            candidato = slugify(self.slug) or slugify(self.titulo) or "servicio"
            if candidato != self.slug:
                self.slug = candidato
            if Servicio.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = self._generar_slug()

        if self.comentarios_admin:
            self.comentarios_admin = self.comentarios_admin.strip()

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        if self.categoria_id and (
            not self.categoria.aprobada or not self.categoria.activa
        ):
            raise ValidationError(
                {
                    "categoria": "La categoría debe estar aprobada y activa."
                }
            )

        requiere_ubicacion = self.formato in (
            self.FORMATO_PRESENCIAL,
            self.FORMATO_SEMIPRESENCIAL,
        )
        if requiere_ubicacion and not self.ubicacion.strip():
            raise ValidationError(
                {"ubicacion": "La ubicación es obligatoria para presencial o semipresencial."}
            )

        if self.precio is not None and self.precio < 0:
            raise ValidationError({"precio": "El precio debe ser mayor o igual a 0."})

        if self.estado == self.ESTADO_EN_REVISION:
            if not self.profesional or self.profesional.estado != Profesional.ESTADO_APROBADO:
                raise ValidationError(
                    {
                        "estado": (
                            "Solo profesionales aprobados pueden enviar servicios a revisión."
                        )
                    }
                )
            campos_obligatorios = [
                self.titulo,
                self.descripcion_corta,
                self.descripcion_larga,
                self.formato,
            ]
            if not all(campos_obligatorios):
                raise ValidationError(
                    "Para enviar a revisión se requieren título, descripciones y formato."
                )
            if self.precio is None:
                raise ValidationError({"precio": "El precio es obligatorio."})
            if not self.categoria_id:
                raise ValidationError({"categoria": "La categoría es obligatoria."})

    def publicar(self, profesional_usuario=None):
        """Pasa de borrador o devuelto a en revisión."""
        if self.estado not in (self.ESTADO_BORRADOR, self.ESTADO_DEVUELTO):
            raise ValueError("Solo se puede publicar un borrador o un servicio devuelto.")
        self.estado = self.ESTADO_EN_REVISION
        self.comentarios_admin = ""
        self.fecha_publicacion = timezone.now()
        self.fecha_revision = None
        self.revisado_por = None
        self.save()
        return self

    def aprobar(self, admin_usuario=None):
        if self.estado != self.ESTADO_EN_REVISION:
            raise ValueError("Solo se puede aprobar un servicio en revisión.")
        self.estado = self.ESTADO_APROBADO
        self.comentarios_admin = ""
        self.fecha_revision = timezone.now()
        self.revisado_por = admin_usuario
        self.save()
        return self

    def devolver(self, admin_usuario=None, comentarios=""):
        comentarios = (comentarios or "").strip()
        if self.estado != self.ESTADO_EN_REVISION:
            raise ValueError("Solo se puede devolver un servicio en revisión.")
        if not comentarios:
            raise ValidationError(
                {"comentarios_admin": "Es obligatorio escribir comentarios al devolver."}
            )
        self.estado = self.ESTADO_DEVUELTO
        self.comentarios_admin = comentarios
        self.fecha_revision = timezone.now()
        self.revisado_por = admin_usuario
        self.save()
        return self

    def rechazar(self, admin_usuario=None, comentarios=""):
        comentarios = (comentarios or "").strip()
        if self.estado != self.ESTADO_EN_REVISION:
            raise ValueError("Solo se puede rechazar un servicio en revisión.")
        if not comentarios:
            raise ValidationError(
                {"comentarios_admin": "Es obligatorio escribir comentarios al rechazar."}
            )
        self.estado = self.ESTADO_RECHAZADO
        self.comentarios_admin = comentarios
        self.fecha_revision = timezone.now()
        self.revisado_por = admin_usuario
        self.save()
        return self

    def suspender(self, admin_usuario=None):
        self.estado = self.ESTADO_SUSPENDIDO
        self.fecha_revision = timezone.now()
        self.revisado_por = admin_usuario
        self.save()
        return self

    @property
    def es_aprobado(self):
        return self.estado == self.ESTADO_APROBADO


class Entregable(models.Model):
    """Entregable asociado a un servicio."""

    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.CASCADE,
        related_name="entregables",
    )
    nombre = models.CharField(max_length=160)
    descripcion = models.TextField(blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "entregable"
        verbose_name_plural = "entregables"
        ordering = ["orden", "id"]

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        if not self.nombre.strip():
            raise ValidationError({"nombre": "El nombre del entregable es obligatorio."})