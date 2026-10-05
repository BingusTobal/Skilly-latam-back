# Skilly Latam — Backend

Django + DRF sobre MariaDB. Este repositorio es **solo backend**: el frontend
vive en otro repositorio (decision D4 de `docs/CONTEXTO-ARQUITECTURA.docx`).

Reglas de negocio y decisiones: `../docs/CONTEXTO-ARQUITECTURA.docx`
Plan de trabajo por sprint: `../docs/PLAN-ITERACIONES.docx`
Fuente de verdad del stack: `../AGENTS.md`

## Estado

**Sprint 0 (Iteracion 0) — Andamiaje: completo.** 17 tickets.
Sprint 1 (Identidad y Curacion) es el siguiente.

## Requisitos

| Herramienta | Version |
|---|---|
| Python | 3.14+ |
| MariaDB | 11.4 (o la que sea local) |
| Redis | 7 (solo desde el Sprint 3) |
| Docker | para `docker compose up -d` |

## Puesta en marcha

```bash
cd skilly-backend

# 1. Entorno virtual
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Variables de entorno
cp .env.example .env
# Editar .env: DJANGO_SECRET_KEY y DB_PASSWORD son obligatorios en produccion

# 3. Base de datos y Redis
docker compose up -d
# Sin Docker: crear la BD a mano.
#   CREATE DATABASE skilly CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
#   CREATE USER 'skilly'@'localhost' IDENTIFIED BY 'skilly_dev_password';
#   GRANT ALL PRIVILEGES ON skilly.* TO 'skilly'@'localhost';

# 4. Migraciones y datos base
python manage.py migrate
python manage.py cargar_seed

# 5. Arrancar
python manage.py runserver
```

Datos que deja `cargar_seed`: las 5 categorias de los mockups y un
administrador `admin@skillylatam.com` (password por defecto, cambiarlo).
El comando es **idempotente**: se puede correr las veces que haga falta.

| Servicio | URL |
|---|---|
| API | http://127.0.0.1:8000/api/ |
| Admin Django | http://127.0.0.1:8000/admin/ |
| Documentacion OpenAPI | http://127.0.0.1:8000/api/docs/ |
| Health check | http://127.0.0.1:8000/health/ |

## Tests

```bash
python -m pytest                                        # todo
python -m pytest --cov=apps --cov=config --cov-report=term-missing
python -m pytest -m auth                                # solo auth
```

Los tests corren sobre **SQLite en memoria** (`config/settings_test.py`), asi
que no necesitan MariaDB levantado. `pytest.ini` apunta ahi.

## Estructura

```
skilly-backend/
├── manage.py
├── requirements.txt          # dependencias directas
├── requirements.lock.txt     # pip freeze completo
├── pytest.ini                # usa config.settings_test
├── conftest.py               # fixtures compartidas
├── docker-compose.yml        # MariaDB + Redis
├── .env.example              # plantilla; el .env real no se versiona
├── config/
│   ├── settings.py           # configuracion real
│   ├── settings_test.py      # ajustes de test (SQLite en memoria)
│   ├── urls.py               # enrutado raiz
│   ├── vistas.py             # health check
│   ├── celery.py             # Celery, activo en el Sprint 3
│   ├── wsgi.py / asgi.py
└── apps/
    ├── usuarios/             # Usuario (AUTH_USER_MODEL), permisos, JWT
    ├── catalogo/             # Categoria + comando cargar_seed
    ├── postulaciones/        # Sprint 1
    ├── reservas/             # Sprint 3
    ├── pagos/                # Sprint 4
    ├── disputas/             # Sprint 3 (modelo) / 5 (endpoints)
    └── comisiones/           # Sprint 4 (modelo) / 5 (reportes)
```

## Convenciones

- Apps, modelos y campos en **espanol**. No traducir a ingles.
- Permisos desde `apps/usuarios/permisos.py`, aplicados **en la vista**, no
  solo en el serializer.
- Cada RF / INT va como comentario donde se implementa.
- Montos como enteros en CLP, nunca float.
- Estados en `snake_case` en la base de datos.

## Definition of Done por ticket

1. `makemigrations` + `migrate` limpio, sin cambios pendientes.
2. Endpoint documentado en `/api/schema/`.
3. Comentario `RF-XX` / `INTXX` en el codigo.
4. Permiso aplicado explicitamente en la vista.
5. Test del caso feliz + un caso de 403.
6. Ningun campo sensible filtrado (password, RUT de terceros, comision).

## Notas de seguridad

- El `.env` esta en `.gitignore`. `.env.example` si se versiona.
- Sin `DJANGO_SECRET_KEY` y con `DEBUG=0` el arranque falla a proposito.
- `check --deploy` pasa limpio. Cookies seguras, HSTS y SSL redirect se activan
  solos cuando `DEBUG=0`.
- `CORS_ALLOWED_ORIGINS` nunca acepta `*` junto con credenciales; settings
  lanza error si alguien lo intenta.
- El RUT tiene validacion de modulo 11. Los RUT de los mockups son invalidos
  (ver `CONTEXTO-ARQUITECTURA.docx` seccion 9.5), por eso el validador no es
  decorativo.
- El token magico (reserva sin cuenta) guarda **solo el hash SHA-256** en la
  base de datos. La implementacion completa llega en el Sprint 3.