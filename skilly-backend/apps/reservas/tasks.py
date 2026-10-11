"""Tareas de reservas (ticket 3.13)."""
from celery import shared_task

from .services import expirar_vencidas


@shared_task(name="reservas.procesar_vencidas")
def procesar_vencidas():
    """Marca como vencidas las reservas cuyo plazo de respuesta expiró."""
    return expirar_vencidas()
