"""
Backend de autenticacion por email. Ticket 0.17.

Django autentica por username; el usuario custom usa email. Este backend
traduce el identificador que llega del login a la columna email.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        Usuario = get_user_model()
        email = username or kwargs.get("email")
        if not email or not password:
            return None
        try:
            usuario = Usuario.objects.get(email=Usuario.objects.normalize_email(email))
        except Usuario.DoesNotExist:
            # Se ejecuta hashear de todas formas para no filtrar por tiempo.
            Usuario().set_password(password)
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
