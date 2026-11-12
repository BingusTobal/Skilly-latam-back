"""Tareas Celery del módulo de pagos (docs/PAGOS_TRANSBANK.md 6.7)."""
from celery import shared_task

from .services import (
    alertar_autorizaciones_por_vencer,
    conciliar_pagos,
    expirar_pagos_vencidos,
)


@shared_task(name="pagos.expirar_pagos_pendientes")
def tarea_expirar_pagos_pendientes():
    """Cada minuto: expira pagos vencidos y libera el horario de la reserva."""
    return expirar_pagos_vencidos()


@shared_task(name="pagos.conciliar_pagos")
def tarea_conciliar_pagos():
    """Cada 5 minutos: corrige pagos iniciados o capturando sin webhooks."""
    return conciliar_pagos()


@shared_task(name="pagos.alertar_autorizaciones_por_vencer")
def tarea_alertar_autorizaciones_por_vencer():
    """Diaria: deja alerta en logs para autorizaciones cerca del límite."""
    return alertar_autorizaciones_por_vencer()
