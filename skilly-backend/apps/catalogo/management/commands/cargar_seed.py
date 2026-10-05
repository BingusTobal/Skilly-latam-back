"""
Comando cargar_seed. Ticket 0.15.

Carga los datos minimos para poder arrancar el desarrollo:
  - un administrador de plataforma
  - las 5 categorias que aparecen en los mockups

Es idempotente: se puede ejecutar las veces que haga falta sin duplicar.

Uso:
    python manage.py cargar_seed
    python manage.py cargar_seed --admin-email admin@skillylatam.com
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalogo.models import Categoria

# Las 5 categorias que aparecen en docs/mockups/prototipo-admin/ganancias-mes.html
CATEGORIAS_SEED = [
    ("Salud y Bienestar", "salud-y-bienestar"),
    ("Desarrollo software", "desarrollo-software"),
    ("Diseño gráfico", "diseno-grafico"),
    ("Marketing", "marketing"),
    ("Finanzas", "finanzas"),
]

EMAIL_ADMIN_POR_DEFECTO = "admin@skillylatam.com"
PASSWORD_ADMIN_POR_DEFECTO = "SkillyAdmin2026!"


class Command(BaseCommand):
    help = "Carga categorias base y el administrador de plataforma (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-email",
            default=EMAIL_ADMIN_POR_DEFECTO,
            help="Email del administrador de plataforma.",
        )
        parser.add_argument(
            "--admin-password",
            default=PASSWORD_ADMIN_POR_DEFECTO,
            help="Password del administrador. Omitir en produccion.",
        )
        parser.add_argument(
            "--sin-admin",
            action="store_true",
            help="No crear el administrador, solo las categorias.",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        Usuario = get_user_model()

        # --- Categorias ---
        creadas_categorias = 0
        for nombre, slug in CATEGORIAS_SEED:
            _, creada = Categoria.objects.get_or_create(
                slug=slug, defaults={"nombre": nombre, "aprobada": True}
            )
            if creada:
                creadas_categorias += 1

        total_categorias = Categoria.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Categorias: {creadas_categorias} nuevas, {total_categorias} en total."
            )
        )

        # --- Administrador ---
        if opciones["sin_admin"]:
            self.stdout.write("Administrador omitido por --sin-admin.")
            return

        email = opciones["admin_email"].strip().lower()
        if Usuario.objects.filter(email=email).exists():
            self.stdout.write(f"Administrador {email} ya existe.")
            return

        if not opciones["admin_password"]:
            raise CommandError(
                "Se requiere --admin-password para crear el administrador."
            )

        Usuario.objects.create_superuser(
            email=email,
            password=opciones["admin_password"],
            first_name="Administrador",
            last_name="Skilly",
            tipo=Usuario.TIPO_ADMIN,
            is_admin=True,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Administrador creado: {email}")
        )
        if opciones["admin_password"] == PASSWORD_ADMIN_POR_DEFECTO:
            self.stdout.write(
                self.style.WARNING(
                    "Se uso el password por defecto. Cámbialo antes de exponer "
                    "el entorno."
                )
            )