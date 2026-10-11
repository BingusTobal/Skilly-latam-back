"""
Puerto de pagos simulado (Sprint 3).

La integración real con Transbank Webpay Plus es del Sprint 4. Acá solo se deja
la interfaz que usarán las transiciones de la reserva, devolviendo siempre un
resultado simulado y sin tocar ninguna pasarela. El escrow real (autorizado →
retenido → liberado / reembolsado) se implementa en el modelo `Pago` del
Sprint 4.
"""


def autorizar(reserva):
    """Autorización simulada al crear la reserva."""
    return {"estado": "autorizado", "referencia": f"SIM-AUT-{reserva.pk}"}


def liberar(reserva):
    """Liberación simulada al confirmar la entrega."""
    return {
        "estado": "liberado",
        "referencia": f"SIM-LIB-{reserva.pk}",
        "monto_neto": str(reserva.monto_neto),
    }


def reembolsar(reserva, porcentaje):
    """Reembolso simulado al cancelar."""
    return {
        "estado": "reembolsado",
        "referencia": f"SIM-REM-{reserva.pk}",
        "porcentaje": porcentaje,
    }
