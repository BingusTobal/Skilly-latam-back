"""Comando de respaldo para vencer reservas sin Celery/Redis (ticket 3.13)."""
from django.core.management.base import BaseCommand

from apps.reservas.services import expirar_vencidas


class Command(BaseCommand):
    help = "Marca como vencidas las reservas cuyo plazo de respuesta expiró."

    def handle(self, *args, **options):
        total = expirar_vencidas()
        self.stdout.write(
            self.style.SUCCESS(f"Reservas vencidas procesadas: {total}")
        )
