from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.usuarios"
    label = "usuarios"
    verbose_name = "Organizacion, Profesional, Horario y el usuario custom (AUTH_USER_MODEL)."
