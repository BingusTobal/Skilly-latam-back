"""Tareas de reservas (tickets 3.13 y R18)."""
from celery import shared_task

from .services import expirar_vencidas, liberar_entregas_vencidas


@shared_task(name="reservas.procesar_vencidas")
def procesar_vencidas():
    """Marca como vencidas las reservas cuyo plazo de respuesta expiró."""
    return expirar_vencidas()


@shared_task(name="reservas.liberar_entregas_vencidas")
def tarea_liberar_entregas_vencidas():
    """Libera pagos de entregas sin confirmar dentro del plazo de revisión."""
    return liberar_entregas_vencidas()
