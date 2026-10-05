"""
Configuracion de Django para Skilly Latam.

Fuente de verdad del stack: AGENTS.md
Tickets cubiertos: 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.11, 0.13, 0.17
"""
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Las variables de .env se cargan antes de leer cualquier os.environ.
load_dotenv(BASE_DIR / ".env")

import os  # noqa: E402  (debe ir despues de load_dotenv)


def env_bool(nombre, por_defecto=False):
    valor = os.environ.get(nombre)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in ("1", "true", "yes", "si", "on")


def env_list(nombre, por_defecto=""):
    valor = os.environ.get(nombre, por_defecto).strip()
    if not valor:
        return []
    return [item.strip() for item in valor.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# 0.2 Seguridad basica
# ---------------------------------------------------------------------------
# En produccion DJANGO_SECRET_KEY es obligatoria: sin ella no se arranca.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
DEBUG = env_bool("DEBUG", False)

if not DEBUG and not SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY no esta definida. Define una en .env antes de "
        "arrancar con DEBUG=0."
    )

if not SECRET_KEY:
    # Solo desarrollo: clave efimera para que el arranque no falle.
    SECRET_KEY = "django-insecure-solo-desarrollo-no-usar-en-produccion"

# 0.6 Hosts permitidos
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# ---------------------------------------------------------------------------
# 0.10 Estructura de aplicaciones
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

# Orden segun AGENTS.md y el grafo de dependencias de PLAN-ITERACIONES.docx
LOCAL_APPS = [
    "apps.usuarios.apps.UsuariosConfig",
    "apps.catalogo.apps.CatalogoConfig",
    "apps.postulaciones.apps.PostulacionesConfig",
    "apps.reservas.apps.ReservasConfig",
    "apps.pagos.apps.PagosConfig",
    "apps.disputas.apps.DisputasConfig",
    "apps.comisiones.apps.ComisionesConfig",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "storages",
    "anymail",
    "drf_spectacular",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS + THIRD_PARTY_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # corsheaders debe ir antes de cualquier middleware que pueda responder.
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# 0.3 Base de datos MariaDB
# ---------------------------------------------------------------------------
DB_ENGINE = os.environ.get("DB_ENGINE", "django.db.backends.mysql").strip()

if DB_ENGINE == "django.db.backends.sqlite3":
    # Solo para tests locales donde no hay MariaDB levantado.
    # La app real corre siempre sobre MariaDB.
    #
    # DB_NAME se respeta también aquí (igual que en el bloque de MariaDB). Con
    # el path fijo, `DB_NAME=/tmp/x.sqlite3 manage.py migrate` migraba en
    # silencio la base de siempre y la base desechable quedaba vacía, lo que
    # hace imposible probar migraciones sobre una base limpia.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DB_NAME", BASE_DIR / "db.sqlite3"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DB_NAME", "skilly"),
            "USER": os.environ.get("DB_USER", "skilly"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
            "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "usuarios.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# 0.5 Internacionalizacion y zona horaria
# ---------------------------------------------------------------------------
# CRITICO: el calculo de slots (ticket 3.1) depende de USE_TZ=True y de que la
# hora local de negocio sea America/Santiago. No cambiar sin revisar reservas.
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Archivos estaticos y medios
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# 0.7 Almacenamiento S3
# ---------------------------------------------------------------------------
# En produccion Amazon S3; en desarrollo backend local. El codigo de la app
# es el mismo en ambos casos.
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "us-east-1")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL") or None
AWS_S3_ADDRESSING_STYLE = os.environ.get("AWS_S3_ADDRESSING_STYLE", "auto")
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_S3_SIGNATURE_VERSION = "s3v4"
# Los certificados y la evidencia de disputas son privados.
AWS_PRESIGNED_EXPIRE = int(os.environ.get("AWS_PRESIGNED_EXPIRE", "900"))

if os.environ.get("USAR_S3", "").strip().lower() in ("1", "true", "yes", "si", "on"):
    if not AWS_STORAGE_BUCKET_NAME:
        raise RuntimeError("USAR_S3=1 requiere definir AWS_STORAGE_BUCKET_NAME en .env")
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}

# ---------------------------------------------------------------------------
# 0.8 Correo transaccional
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "contacto@skillylatam.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

if EMAIL_BACKEND.startswith("django_ses"):
    # Amazon SES via django-anymail. Verificar el dominio en SES antes de prod.
    AWS_SES_ACCESS_KEY_ID = os.environ.get("AWS_SES_ACCESS_KEY_ID", "")
    AWS_SES_SECRET_ACCESS_KEY = os.environ.get("AWS_SES_SECRET_ACCESS_KEY", "")
    AWS_SES_REGION_NAME = os.environ.get("AWS_SES_REGION_NAME", "us-east-1")

EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))

# Frontend en otro repositorio (D4). Se usa para armar los enlaces de los
# correos (restablecer contraseña, confirmar token mágico de la reserva D7).
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# ---------------------------------------------------------------------------
# 0.6 CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]
CORS_EXPOSE_HEADERS = ["content-disposition"]

# Nunca comodines con credenciales: CORS_ALLOWED_ORIGINS se define por .env.
if CORS_ALLOW_CREDENTIALS and "*" in CORS_ALLOWED_ORIGINS:
    raise RuntimeError(
        "CORS_ALLOWED_ORIGINS no puede contener '*' cuando "
        "CORS_ALLOW_CREDENTIALS esta activo."
    )

# ---------------------------------------------------------------------------
# REST Framework (0.13 RBAC se resuelve en apps/usuarios/permisos.py)
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.usuarios.permisos.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ]

SPECTACULAR_SETTINGS = {
    "TITLE": "Skilly Latam API",
    "DESCRIPTION": (
        "Marketplace de servicios con precio fijo. Documentacion generada "
        "automaticamente; los RF/INT viven en docs/Informe_del_Sistema.xlsx."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ---------------------------------------------------------------------------
# 0.17 JWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "token_type",
}

AUTHENTICATION_BACKENDS = [
    "apps.usuarios.backends.EmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# ---------------------------------------------------------------------------
# 0.9 Constantes de negocio
# ---------------------------------------------------------------------------
# Vienen del .env para poder ajustarlas sin redeploy. Los valores por defecto
# son los aprobados en CONTEXTO-ARQUITECTURA.docx (seccion 12.1).

# R12: plazo de respuesta del profesional antes de que la reserva venza.
PLAZO_RESPUESTA_PROFESIONAL_HORAS = int(
    os.environ.get("PLAZO_RESPUESTA_PROFESIONAL_HORAS", "6")
)

# R12: recordatorio al profesional antes de que venza.
PLAZO_RECORDATORIO_HORAS = int(os.environ.get("PLAZO_RECORDATORIO_HORAS", "4"))

# R18: auto liberacion del pago si la organizacion no confirma la entrega.
PLAZO_REVISION_ORGANIZACION_DIAS = int(
    os.environ.get("PLAZO_REVISION_ORGANIZACION_DIAS", "5")
)

# Ventana de autorizacion de Transbank Diferido (aprox 7 dias).
# 4.9 exige re-autorizacion cuando la reserva sigue pendiente al vencer.
DIAS_VENTANA_AUTORIZACION_WEBPAY = int(
    os.environ.get("DIAS_VENTANA_AUTORIZACION_WEBPAY", "7")
)

# D7: duracion del token magico de la reserva sin cuenta (horas).
TOKEN_MAGICO_HORAS = int(os.environ.get("TOKEN_MAGICO_HORAS", "24"))

MONTO_MINIMO_SERVICIO = int(os.environ.get("MONTO_MINIMO_SERVICIO", "5000"))
TASA_COMISION_DEFECTO = float(os.environ.get("TASA_COMISION_DEFECTO", "0.10"))

# D3: politica de cancelacion hasta el kickoff.
HORAS_CANCELACION_SIN_PENALIDAD = int(
    os.environ.get("HORAS_CANCELACION_SIN_PENALIDAD", "24")
)
PORCENTAJE_REEMBOLSO_CANCELACION_TARDIA = int(
    os.environ.get("PORCENTAJE_REEMBOLSO_CANCELACION_TARDIA", "90")
)

# R5: unicos formatos de ejecucion permitidos.
FORMATOS_EJECUCION = ("remoto", "presencial", "hibrido")

# ---------------------------------------------------------------------------
# Celery (Sprint 3, ticket 3.13) - se declara en Sprint 0 para tener Redis pronto
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIMEZONE = TIME_ZONE
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE_CANONICAL = True
CELERY_BEAT_SCHEDULE = {}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "estandar": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "consola": {"class": "logging.StreamHandler", "formatter": "estandar"},
    },
    "root": {"handlers": ["consola"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["consola"], "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# 0.6 Endurecimiento de cookies y transporte en produccion
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")