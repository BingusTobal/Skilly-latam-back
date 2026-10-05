"""
Modelos de la app usuarios.
Ticket cubierto: 0.11 (AUTH_USER_MODEL).

Organizacion, Profesional y Horario llegan en el Sprint 1; aqui solo el usuario
base, que es lo unico que Sprint 0 necesita para poder migrar y autenticar.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.db import models
from django.utils import timezone


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
