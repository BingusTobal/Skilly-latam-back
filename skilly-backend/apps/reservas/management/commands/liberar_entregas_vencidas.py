"""Comando de respaldo para auto-liberar entregas sin Celery/Redis (R18)."""
from django.core.management.base import BaseCommand

from apps.reservas.services import liberar_entregas_vencidas


class Command(BaseCommand):
    help = "Libera pagos de entregas que la organización no confirmó en el plazo."

    def handle(self, *args, **options):
        total = liberar_entregas_vencidas()
        self.stdout.write(
            self.style.SUCCESS(f"Entregas liberadas automáticamente: {total}")
        )
