"""
Modelos de postulaciones. Tickets 1.4 y 1.5.

Regla R9: la moderación de la POSTULACION y la de los CERTIFICADOS son
independientes. Aprobar la postulación no aprueba los documentos, y un
certificado aprobado no aprueba la postulación. Son dos estados separados a
propósito, no un atajo.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def limite_archivo_certificado():
    """5 MB, formato PDF o imagen."""
    return 5 * 1024 * 1024


class Postulacion(models.Model):
    """Postulación de un profesional. Ticket 1.4.

    Un profesional puede tener varias postulaciones a lo largo del tiempo
    (por ejemplo, si le devuelven una y la reenvía), pero solo una puede estar
    pendiente a la vez. La restricción es de aplicación porque MySQL no
    soporta índices filtrados; el test la verifica.
    """

    ESTADO_PENDIENTE = "pendiente"
    ESTADO_APROBADA = "aprobada"
    ESTADO_RECHAZADA = "rechazada"
    ESTADO_DEVUELTA = "devuelta"
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADA, "Aprobada"),
        (ESTADO_RECHAZADA, "Rechazada"),
        (ESTADO_DEVUELTA, "Devuelta"),
    ]

    TERMINALES = {ESTADO_APROBADA, ESTADO_RECHAZADA}
    TRANSICIONES = {
        ESTADO_PENDIENTE: {ESTADO_APROBADA, ESTADO_RECHAZADA, ESTADO_DEVUELTA},
        ESTADO_DEVUELTA: {ESTADO_PENDIENTE, ESTADO_APROBADA, ESTADO_RECHAZADA},
        ESTADO_APROBADA: set(),
        ESTADO_RECHAZADA: set(),
    }

    profesional = models.ForeignKey(
        "usuarios.Profesional", on_delete=models.CASCADE, related_name="postulaciones"
    )

    estado = models.CharField(
        max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE, db_index=True
    )

    # Comentarios del admin, visibles para el profesional (R4 lo pide para
    # servicios; acá es el mismo patrón para la postulación).
    comentarios_admin = models.TextField(
        blank=True, help_text="Se muestra al profesional al devolver o rechazar."
    )

    # Qué pidió el profesional en su postulación.
    experiencia = models.TextField(blank=True)
    especialidad = models.CharField(max_length=150, blank=True)

    fecha_postulacion = models.DateTimeField(auto_now_add=True)
    fecha_revision = models.DateTimeField(null=True, blank=True)
    revisada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="postulaciones_revisadas",
    )

    class Meta:
        verbose_name = "postulación"
        verbose_name_plural = "postulaciones"
        ordering = ["-fecha_postulacion"]

    def __str__(self):
        return f"{self.profesional.nombre_completo} ({self.get_estado_display()})"

    def save(self, *args, **kwargs):
        if self.comentarios_admin:
            # Normaliza para no guardar espacios sobrantes y comparar siempre igual.
            self.comentarios_admin = self.comentarios_admin.strip()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        # Devolver o rechazar sin comentarios no sirve de nada: el
        # profesional no sabría qué corregir.
        if self.estado in (self.ESTADO_DEVUELTA, self.ESTADO_RECHAZADA):
            if not self.comentarios_admin.strip():
                raise ValidationError(
                    {
                        "comentarios_admin": (
                            "Es obligatorio escribir comentarios al devolver o "
                            "rechazar una postulación."
                        )
                    }
                )
        # Solo una postulación pendiente por profesional.
        if self.estado == self.ESTADO_PENDIENTE:
            otras = Postulacion.objects.filter(
                profesional_id=self.profesional_id, estado=self.ESTADO_PENDIENTE
            )
            if self.pk:
                otras = otras.exclude(pk=self.pk)
            if otras.exists():
                raise ValidationError(
                    "El profesional ya tiene una postulación pendiente."
                )

    # --- Transiciones ------------------------------------------------------
    def _puede_transicionar_a(self, nuevo):
        permitidos = self.TRANSICIONES.get(self.estado, set())
        return nuevo in permitidos

    def _aplicar(self, nuevo, admin_usuario=None, comentarios=""):
        if nuevo not in self.TRANSICIONES:
            raise ValueError(f"Estado desconocido: {nuevo}")
        # Repisar el mismo estado no es una transición: es una operación que
        # no debería existir. Se rechaza acá y no en la vista, para que la
        # regla valga llegue por donde llegue la llamada.
        if nuevo == self.estado:
            raise ValueError(f"La postulación ya está en estado '{nuevo}'.")
        if not self._puede_transicionar_a(nuevo):
            raise ValueError(f"No se puede pasar de '{self.estado}' a '{nuevo}'.")
        if comentarios:
            self.comentarios_admin = comentarios.strip()

        # La validación exige comentarios en devolver/rechazar.
        if nuevo in (self.ESTADO_DEVUELTA, self.ESTADO_RECHAZADA):
            if not self.comentarios_admin:
                raise ValidationError(
                    "Es obligatorio escribir comentarios al devolver o rechazar."
                )

        self.estado = nuevo
        self.fecha_revision = timezone.now()
        self.revisada_por = admin_usuario
        self.save()

        # El estado del profesional sigue al de su postulación.
        self._sincronizar_estado_profesional()
        return self

    def aprobar(self, admin_usuario=None):
        """Aprueba la postulación. NO toca los certificados (R9)."""
        return self._aplicar(self.ESTADO_APROBADA, admin_usuario)

    def rechazar(self, admin_usuario=None, comentarios=""):
        return self._aplicar(self.ESTADO_RECHAZADA, admin_usuario, comentarios)

    def devolver(self, admin_usuario=None, comentarios=""):
        return self._aplicar(self.ESTADO_DEVUELTA, admin_usuario, comentarios)

    def reenviar(self, profesional_usuario=None):
        """El profesional reenvía una postulación devuelta."""
        if self.estado != self.ESTADO_DEVUELTA:
            raise ValueError("Solo se puede reenviar una postulación devuelta.")
        self.estado = self.ESTADO_PENDIENTE
        self.comentarios_admin = ""
        self.fecha_revision = None
        self.revisada_por = None
        self.save()
        self._sincronizar_estado_profesional()
        return self

    def _sincronizar_estado_profesional(self):
        from apps.usuarios.models import Profesional

        profesional = self.profesional
        if self.estado == self.ESTADO_APROBADA:
            nuevo = Profesional.ESTADO_APROBADO
        elif self.estado == self.ESTADO_RECHAZADA:
            nuevo = Profesional.ESTADO_RECHAZADO
        elif self.estado in (self.ESTADO_DEVUELTA, self.ESTADO_PENDIENTE):
            nuevo = Profesional.ESTADO_POSTULANDO
        else:
            return

        if profesional.estado != nuevo:
            profesional.estado = nuevo
            profesional.save()

    @property
    def tiene_certificados_sin_revisar(self):
        return self.certificados.filter(estado=Certificado.ESTADO_SIN_REVISOR).exists()

    @property
    def esta_pendiente(self):
        return self.estado == self.ESTADO_PENDIENTE


class Certificado(models.Model):
    """Certificado del profesional. Ticket 1.5.

    Cuatro estados (R9):
      - verificado_automatico: el perfil de LinkedIn. OJO: lo que se valida es
        el FORMATO de la URL, porque LinkedIn no ofrece API pública para
        validar un perfil. Decisión 3 del Sprint 1.
      - sin_reviewer: cualquier otro documento, esperando moderación manual.
      - aprobado / rechazado: decisión del admin sobre ese documento.
    """

    ESTADO_VERIFICADO_AUTOMATICO = "verificado_automatico"
    ESTADO_SIN_REVISOR = "sin_reviewer"
    ESTADO_APROBADO = "aprobado"
    ESTADO_RECHAZADO = "rechazado"
    ESTADO_CHOICES = [
        (ESTADO_VERIFICADO_AUTOMATICO, "Verificado automáticamente"),
        (ESTADO_SIN_REVISOR, "Sin revisar"),
        (ESTADO_APROBADO, "Aprobado"),
        (ESTADO_RECHAZADO, "Rechazado"),
    ]

    TIPO_LINKEDIN = "linkedin"
    TIPO_OTRO = "otro"
    TIPO_CHOICES = [
        (TIPO_LINKEDIN, "LinkedIn"),
        (TIPO_OTRO, "Otro documento"),
    ]

    postulacion = models.ForeignKey(
        Postulacion, on_delete=models.CASCADE, related_name="certificados"
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_OTRO)

    nombre = models.CharField(max_length=150, help_text="Ej: Título profesional.")
    # El archivo es obligatorio para documentos, no para LinkedIn.
    archivo = models.FileField(
        upload_to="certificados/%Y/%m/", blank=True, max_length=5 * 1024 * 1024
    )

    # Para LinkedIn se guarda la URL aquí en lugar de un archivo.
    enlace = models.URLField(max_length=500, blank=True)

    estado = models.CharField(max_length=30, choices=ESTADO_CHOICES, db_index=True)

    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="certificados_revisados",
    )
    comentario_revisor = models.TextField(blank=True)
    fecha_revision = models.DateTimeField(null=True, blank=True)
    cargado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "certificado"
        verbose_name_plural = "certificados"
        ordering = ["-cargado_en"]

    def __str__(self):
        return f"{self.nombre} ({self.get_estado_display()})"

    def clean(self):
        super().clean()
        if self.tipo == self.TIPO_LINKEDIN:
            if not self.enlace:
                raise ValidationError({"enlace": "LinkedIn requiere la URL del perfil."})
        else:
            if not self.archivo:
                raise ValidationError(
                    {"archivo": "Un documento requiere un archivo adjunto."}
                )

    # --- Transiciones de moderación (independientes de la postulación) -----
    def aprobar(self, admin_usuario=None):
        if self.estado == self.ESTADO_VERIFICADO_AUTOMATICO:
            raise ValidationError("El perfil de LinkedIn no requiere moderación.")
        self.estado = self.ESTADO_APROBADO
        self.fecha_revision = timezone.now()
        self.revisado_por = admin_usuario
        self.save()
        return self

    def rechazar(self, admin_usuario=None, comentario=""):
        if self.estado == self.ESTADO_VERIFICADO_AUTOMATICO:
            raise ValidationError("El perfil de LinkedIn no requiere moderación.")
        self.estado = self.ESTADO_RECHAZADO
        self.comentario_revisor = (comentario or "").strip()
        self.fecha_revision = timezone.now()
        self.revisado_por = admin_usuario
        self.save()
        return self

    @property
    def es_linkedin(self):
        return self.tipo == self.TIPO_LINKEDIN

    @property
    def requiere_moderacion(self):
        return self.estado == self.ESTADO_SIN_REVISOR
