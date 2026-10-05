"""
Modelos de la app usuarios.
Tickets cubiertos: 0.11 (AUTH_USER_MODEL), 1.1 (Organizacion), 1.2 (Profesional),
1.3 (Horario).

Organizacion y Profesional se crean en el Sprint 1; aqui solo el usuario base,
que es lo unico que Sprint 0 necesita para poder migrar y autenticar.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.deconstruct import deconstructible


def validar_rut(valor):
    """Valida un RUT chileno (modulo 11). Tickets 1.1 y 0.13.

    Los RUT de los mockups son invalidos (ver docs/CONTEXTO-ARQUITECTURA.docx
    seccion 9.5), asi que este validador no es decorativo: es el que impide
    sembrar datos basura.
    """
    if not valor:
        return

    limpio = str(valor).replace(".", "").replace("-", "").upper()
    if len(limpio) < 2:
        raise ValueError("El RUT es demasiado corto.")

    cuerpo, verificador = limpio[:-1], limpio[-1]
    if not cuerpo.isdigit():
        raise ValueError("El RUT debe contener solo digitos antes del verificador.")

    # El cuerpo no puede empezar con 0.
    if cuerpo[0] == "0":
        raise ValueError("El RUT no puede comenzar en 0.")

    pesos = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5, 6, 7, 8, 9]
    suma = sum(int(digito) * pesos[i] for i, digito in enumerate(cuerpo[-len(pesos):]))
    calculado = 11 - (suma % 11)
    esperado = {10: "K", 11: "0"}.get(calculado, str(calculado))

    if str(esperado) != str(verificador):
        raise ValueError(
            f"RUT invalido: verificador incorrecto (se esperaba {esperado})."
        )


class UsuarioManager(BaseUserManager):
    """Manager que crea usuarios con email como identificador."""

    use_in_migrations = True

    def _crear_usuario(self, email, password, **extra):
        if not email:
            raise ValueError("El email es obligatorio.")
        email = self.normalize_email(email)
        usuario = self.model(email=email, **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._crear_usuario(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)

        if extra.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")

        return self._crear_usuario(email, password, **extra)


class Usuario(AbstractUser):
    """Usuario custom. Ticket 0.11.

    Cambia el identificador de login de username a email, que es lo que usan
    organizaciones y profesionales.
    """

    username = None
    email = models.EmailField("email", unique=True)

    # El administrador del panel (RF de administracion).
    is_admin = models.BooleanField(
        "es administrador",
        default=False,
        help_text="Puede entrar al panel de administracion y moderar.",
    )

    # Rol de la cuenta. La pertenencia a una organizacion o a un perfil
    # profesional se resuelve en sus propios modelos (Sprint 1).
    TIPO_ORGANIZACION = "organizacion"
    TIPO_PROFESIONAL = "profesional"
    TIPO_ADMIN = "admin"
    TIPO_CHOICES = [
        (TIPO_ORGANIZACION, "Organización"),
        (TIPO_PROFESIONAL, "Profesional"),
        (TIPO_ADMIN, "Administrador"),
    ]
    tipo = models.CharField(
        "tipo de cuenta",
        max_length=20,
        choices=TIPO_CHOICES,
        default=TIPO_PROFESIONAL,
    )

    # Token magico de la reserva sin cuenta (D7). Se guarda el hash, nunca
    # el token en claro. Se implementa en el Sprint 3, ticket 3.5.
    token_magico_hash = models.CharField(max_length=64, blank=True, null=True, unique=True)
    token_magico_expira = models.DateTimeField(blank=True, null=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def nombre_completo(self):
        completo = f"{self.first_name} {self.last_name}".strip()
        return completo or self.email

    @property
    def es_admin_plataforma(self):
        return bool(self.is_admin or self.is_superuser)

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def save(self, *args, **kwargs):
        self.email = self.__class__.objects.normalize_email(self.email)
        super().save(*args, **kwargs)

    # --- Token magico (Sprint 3) -------------------------------------------
    def generar_token_magico(self, horas_validez=None):
        """Genera un token de un solo uso y guarda solo su hash SHA-256.

        Se deja el metodo aqui para que la app de reservas lo use en el
        Sprint 3 (ticket 3.5). Nunca se persiste el token en claro.
        """
        import hashlib
        import secrets

        from django.conf import settings

        if horas_validez is None:
            horas_validez = getattr(settings, "TOKEN_MAGICO_HORAS", 24)

        token = secrets.token_urlsafe(32)
        self.token_magico_hash = self._hash_token(token)
        self.token_magico_expira = timezone.now() + timezone.timedelta(
            hours=horas_validez
        )
        self.save(update_fields=["token_magico_hash", "token_magico_expira"])
        return token

    @staticmethod
    def _hash_token(token):
        import hashlib

        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def token_magico_valido(self, token):
        """Valida el token magico: debe existir, no estar expirado y coincidir."""
        if not token or not self.token_magico_hash:
            return False
        if not self.token_magico_expira or self.token_magico_expira < timezone.now():
            return False
        return self._hash_token(token) == self.token_magico_hash

    def invalidar_token_magico(self):
        self.token_magico_hash = None
        self.token_magico_expira = None
        self.save(update_fields=["token_magico_hash", "token_magico_expira"])


# Se deja el validador disponible para el Sprint 1 (Organizacion y Profesional).
validar_rut.__name__ = "validar_rut"
VALIDADOR_RUT = RegexValidator(
    r"^\d{7,8}-?[0-9Kk]$", "Formato de RUT inválido (ej: 12.345.678-5)."
)


@deconstructible
class ValidadorRut:
    """Validador de Django que envuelve validar_rut (módulo 11).

    Decisión 4 del Sprint 1: RUT se valida igual en Organizacion y Profesional.

    Es `@deconstructible` porque Django tiene que poder serializar el validador
    dentro de una migración; una clase normal no se puede escribir en un
    archivo de migración.
    """

    mensaje = "RUT inválido: el dígito verificador no corresponde."

    def __call__(self, valor):
        if not valor:
            return
        try:
            validar_rut(valor)
        except ValueError as exc:
            raise ValidationError(str(exc), code="rut_invalido") from exc


VALIDADOR_RUT_MODULO11 = ValidadorRut()


# ===========================================================================
# Sprint 1 — ticket 1.1
# ===========================================================================
class Organizacion(models.Model):
    """Organización que contrata servicios. Ticket 1.1.

    `usuario` es NULLABLE desde el inicio (decisión D10): la reserva sin cuenta
    crea una organización invitada que todavía no tiene usuario. Si se hiciera
    la migración más tarde, se tocaría una tabla ya viva.
    """

    MODO_REGISTRADA = "registrada"
    MODO_INVITADA = "invitada"
    MODO_CHOICES = [
        (MODO_REGISTRADA, "Registrada"),
        (MODO_INVITADA, "Invitada"),
    ]

    nombre = models.CharField(max_length=200)
    giro = models.CharField(
        max_length=150, blank=True, help_text="A qué se dedica la organización."
    )
    nombre_contacto = models.CharField(max_length=150)
    email_contacto = models.EmailField()
    telefono = models.CharField(max_length=30, blank=True)

    # Decisión 4: RUT con validación de módulo 11, igual que en Profesional.
    rut = models.CharField(
        "RUT",
        max_length=12,
        unique=True,
        validators=[VALIDADOR_RUT_MODULO11],
        help_text="Sin puntos ni guiones, o con ellos: se normaliza al guardar.",
    )

    # NULLABLE a proposito (D10).
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organizacion",
    )

    modo = models.CharField(
        max_length=20,
        choices=MODO_CHOICES,
        default=MODO_REGISTRADA,
        help_text="'invitada' = creada por una reserva sin cuenta (D7).",
    )

    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "organización"
        verbose_name_plural = "organizaciones"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        # Normaliza el RUT: sin puntos ni guiones, siempre.
        if self.rut:
            self.rut = self.rut.replace(".", "").replace("-", "").upper()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        # Una organización registrada debe tener usuario.
        if self.modo == self.MODO_REGISTRADA and self.usuario_id is None:
            raise ValidationError(
                {"modo": "Una organización registrada debe tener un usuario asociado."}
            )

    @property
    def es_invitada(self):
        return self.modo == self.MODO_INVITADA

    @property
    def rutsin_puntos(self):
        return self.rut


# ===========================================================================
# Sprint 1 — ticket 1.2
# ===========================================================================
class Profesional(models.Model):
    """Perfil profesional. Ticket 1.2.

    El estado vive acá y no en la Postulación: la postulación es el trámite,
    el estado es la habilitación para publicar. Un profesional aprobado puede
    ser suspendido después sin que su postulación cambie.
    """

    ESTADO_POSTULANDO = "postulando"
    ESTADO_APROBADO = "aprobado"
    ESTADO_RECHAZADO = "rechazado"
    ESTADO_SUSPENDIDO = "suspendido"
    ESTADO_CHOICES = [
        (ESTADO_POSTULANDO, "Postulando"),
        (ESTADO_APROBADO, "Aprobado"),
        (ESTADO_RECHAZADO, "Rechazado"),
        (ESTADO_SUSPENDIDO, "Suspendido"),
    ]

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profesional",
    )
    nombre_completo = models.CharField(max_length=150)
    bio = models.TextField(blank=True, help_text="Presentación breve.")
    telefono = models.CharField(max_length=30, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)

    # Decisión 4: RUT con módulo 11, igual que en Organizacion.
    rut = models.CharField(
        "RUT",
        max_length=12,
        unique=True,
        validators=[VALIDADOR_RUT_MODULO11],
    )

    linkedin_url = models.URLField(
        max_length=255,
        blank=True,
        help_text="Se valida el formato de la URL, no el perfil real (decisión 3).",
    )

    estado = models.CharField(
        max_length=20, choices=ESTADO_CHOICES, default=ESTADO_POSTULANDO, db_index=True
    )

    disponibilidad = models.CharField(
        max_length=20,
        choices=[
            ("inmediata", "Inmediata"),
            ("semanal", "Semanal"),
            ("mensual", "Mensual"),
        ],
        default="inmediata",
    )

    # Cambia cuando el admin aprueba o rechaza, para ordenar la cola.
    fecha_estado = models.DateTimeField(auto_now=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "profesional"
        verbose_name_plural = "profesionales"
        ordering = ["nombre_completo"]

    def __str__(self):
        return self.nombre_completo

    def save(self, *args, **kwargs):
        if self.rut:
            self.rut = self.rut.replace(".", "").replace("-", "").upper()
        super().save(*args, **kwargs)

    @property
    def esta_aprobado(self):
        return self.estado == self.ESTADO_APROBADO

    @property
    def puede_publicar(self):
        """R4: publicar exige profesional aprobado y categoría aprobada."""
        return self.esta_aprobado


# ===========================================================================
# Sprint 1 — ticket 1.3
# ===========================================================================
class Horario(models.Model):
    """Horario semanal del profesional. Ticket 1.3.

    Vive en la app usuarios (decisión D9): es un atributo del profesional, no
    del catálogo. El cálculo de slots del Sprint 3 (3.1) lo usa junto con las
    reservas vigentes.
    """

    DIAS = [
        (0, "Lunes"),
        (1, "Martes"),
        (2, "Miércoles"),
        (3, "Jueves"),
        (4, "Viernes"),
        (5, "Sábado"),
        (6, "Domingo"),
    ]

    profesional = models.ForeignKey(
        Profesional, on_delete=models.CASCADE, related_name="horarios"
    )
    dia_semana = models.PositiveSmallIntegerField(choices=DIAS)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "horario"
        verbose_name_plural = "horarios"
        ordering = ["profesional", "dia_semana", "hora_inicio"]
        # Sin UniqueConstraint a propósito: bloquearía (profesional, día,
        # inicio, fin) aunque el bloque esté inactivo, y un profesional que
        # desactiva un bloque y después quiere volver a crearlo se encontraría
        # con un error de base de datos. El solapamiento y la duplicación se
        # detectan en `clean()`, que es donde además se puede dar el mensaje
        # útil. Ver ticket 1.3.

    def __str__(self):
        inicio = self.hora_inicio
        fin = self.hora_fin
        # strftime solo existe en objetos time; si se asignó un string desde el
        # admin o un test, se muestra tal cual en vez de romper.
        if hasattr(inicio, "strftime"):
            rango = f"{inicio.strftime('%H:%M')}–{fin.strftime('%H:%M')}"
        else:
            rango = f"{inicio}–{fin}"
        return f"{self.get_dia_semana_display()}: {rango}"

    def clean(self):
        super().clean()
        if self.hora_fin <= self.hora_inicio:
            raise ValidationError(
                {"hora_fin": "La hora de fin debe ser posterior a la de inicio."}
            )
        if not (0 <= self.dia_semana <= 6):
            raise ValidationError({"dia_semana": "Día de semana inválido."})
        # Un profesional no puede tener dos bloques que se pisen el mismo día.
        solapados = Horario.objects.filter(
            profesional_id=self.profesional_id,
            dia_semana=self.dia_semana,
            activo=True,
            hora_inicio__lt=self.hora_fin,
            hora_fin__gt=self.hora_inicio,
        )
        if self.pk:
            solapados = solapados.exclude(pk=self.pk)
        if solapados.exists():
            raise ValidationError(
                {
                    "hora_inicio": (
                        "Este bloque se solapa con un horario existente del "
                        "mismo día."
                    )
                }
            )