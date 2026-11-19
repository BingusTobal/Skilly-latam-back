# Skilly Latam — Backend

API de Skilly Latam (marketplace de servicios con precio fijo).

## Stack

- Django + Django REST Framework
- `djangorestframework-simplejwt` (JWT)
- MariaDB
- Amazon S3 / SES en producción; archivos locales y correo a consola en desarrollo
- Transbank Webpay Plus (sandbox) como pasarela de pago

La fuente de verdad del stack y las reglas de negocio está en `AGENTS.md`.
Los requerimientos, actores y mockups de referencia están en `docs/`.

## Requisitos

- Python 3.14 (probado en este repo)
- MariaDB 11+
- Redis solo si vas a trabajar con Celery
- Node.js no es necesario para el backend

## Configuración

Desde la raíz del repo:

```bash
cd skilly-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con tu clave local y tus datos de MariaDB. Los valores por defecto
de la plantilla son:

```env
DB_ENGINE=django.db.backends.mysql
DB_NAME=skilly
DB_USER=skilly
DB_PASSWORD=cambia-esta-clave
DB_HOST=127.0.0.1
DB_PORT=3306
```

## Base de datos local

Crea la base y el usuario en MariaDB:

```sql
CREATE DATABASE skilly CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'skilly'@'127.0.0.1' IDENTIFIED BY 'skilly_dev_password';
GRANT ALL PRIVILEGES ON skilly.* TO 'skilly'@'127.0.0.1';
FLUSH PRIVILEGES;
```

Ajusta `DB_PASSWORD` en `.env` para que coincida con el usuario creado.

## Migraciones y datos iniciales

```bash
python manage.py migrate
python manage.py cargar_seed
python manage.py cargar_demo
```

- `cargar_seed` crea las categorías base y el usuario administrador.
- `cargar_demo` crea profesional, organización, horarios y servicios aprobados.
- Ambos comandos son idempotentes.

Usuarios que dejan los comandos anteriores:

| Rol | Email | Password |
|---|---|---|
| Admin | `admin@skillylatam.com` | `SkillyAdmin2026!` |
| Organización | `org@test.skilly` | `OrgTest123!` |
| Profesional | `juan@test.skilly` | `ProfTest123!` |

## Desarrollo

```bash
python manage.py runserver
```

La API queda disponible en:

| Servicio | URL |
|---|---|
| API | `http://127.0.0.1:8000/api/` |
| Admin Django | `http://127.0.0.1:8000/admin/` |
| Documentación OpenAPI | `http://127.0.0.1:8000/api/docs/` |
| Health check | `http://127.0.0.1:8000/health/` |

Si el frontend corre en `http://localhost:5173`, los orígenes ya están
permitidos en `.env.example`.

## Pagos en local

Por defecto `.env.example` usa `PAYMENT_GATEWAY=fake` con
`ALLOW_FAKE_GATEWAY=1`, así que se puede probar el flujo sin Transbank.

Para usar Webpay Plus sandbox:

```env
PAYMENT_GATEWAY=transbank
TRANSBANK_ENV=integration
TRANSBANK_COMMERCE_CODE=<commerce code de integración>
TRANSBANK_API_KEY_SECRET=<api key de integración>
TRANSBANK_RETURN_URL=<URL pública>/api/pagos/transbank/retorno/
```

El `return_url` debe ser públicamente alcanzable; en local se puede exponer el
puerto `8000` con ngrok.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
python -m pytest --cov=apps --cov=config --cov-report=term-missing
```

Los tests usan SQLite en memoria (`config/settings_test.py`), así que no
necesitan MariaDB levantado.

## Estructura

```
skilly-backend/
├── manage.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── config/
│   ├── settings.py
│   ├── settings_test.py
│   └── urls.py
└── apps/
    ├── usuarios/
    ├── catalogo/
    ├── reservas/
    ├── pagos/
    ├── postulaciones/
    ├── disputas/
    └── comisiones/
```
