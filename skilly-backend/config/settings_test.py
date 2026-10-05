"""
Ajustes de prueba. Ticket 0.16.

Los tests no pueden depender de un MariaDB levantado, asi que corren sobre
SQLite en memoria. Los settings de produccion NO se tocan: esto solo redefine
la base de datos y acelera el hasheo de passwords.

Se usa desde pytest.ini:
    DJANGO_SETTINGS_MODULE = config.settings_test
"""
from .settings import *  # noqa: F401,F403

# Base de datos en memoria para cada test.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Nada de llamadas de red durante los tests.
USAR_S3 = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = True

# MD5 es mas rapido que PBKDF2 y suficiente para tests.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

DEBUG = False
ALLOWED_HOSTS = ["*"]

# Sin whitenoise esperando staticfiles compilados.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MIDDLEWARE = [
    m for m in MIDDLEWARE if "whitenoise" not in m.lower()
]  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}