"""
Estados y transiciones del pago (docs/PAGOS_TRANSBANK.md 4.3).

La tabla agrega los estados transitorios `cancelando` y `reembolsando` para no
mantener bloqueos de base de datos durante las llamadas a la pasarela.
"""

INICIADO = "iniciado"
AUTORIZADO = "autorizado"
CAPTURANDO = "capturando"
RETENIDO = "retenido"
LIBERADO = "liberado"
REEMBOLSANDO = "reembolsando"
REEMBOLSADO = "reembolsado"
CANCELANDO = "cancelando"
CANCELADO = "cancelado"
RECHAZADO = "rechazado"
EXPIRADO = "expirado"
REVISION_MANUAL = "revision_manual"

ESTADO_CHOICES = [
    (INICIADO, "Iniciado"),
    (AUTORIZADO, "Autorizado"),
    (CAPTURANDO, "Capturando"),
    (RETENIDO, "Retenido"),
    (LIBERADO, "Liberado"),
    (REEMBOLSANDO, "Reembolsando"),
    (REEMBOLSADO, "Reembolsado"),
    (CANCELANDO, "Cancelando"),
    (CANCELADO, "Cancelado"),
    (RECHAZADO, "Rechazado"),
    (EXPIRADO, "Expirado"),
    (REVISION_MANUAL, "Revisión manual"),
]

TRANSICIONES = {
    INICIADO: {AUTORIZADO, RETENIDO, RECHAZADO, EXPIRADO, REVISION_MANUAL},
    AUTORIZADO: {CAPTURANDO, CANCELANDO, EXPIRADO},
    CAPTURANDO: {RETENIDO, AUTORIZADO, REVISION_MANUAL},
    CANCELANDO: {CANCELADO, AUTORIZADO, REVISION_MANUAL},
    RETENIDO: {LIBERADO, REEMBOLSANDO, REVISION_MANUAL},
    LIBERADO: {REEMBOLSANDO},
    REEMBOLSANDO: {REEMBOLSADO, REVISION_MANUAL},
    REEMBOLSADO: set(),
    CANCELADO: set(),
    RECHAZADO: set(),
    EXPIRADO: set(),
    REVISION_MANUAL: set(),
}

ESTADOS_TERMINALES = {
    REEMBOLSADO,
    CANCELADO,
    RECHAZADO,
    EXPIRADO,
}

# Estados en los que un pago sigue "vivo" y bloquea un nuevo intento.
ESTADOS_VIGENTES = set(TRANSICIONES) - ESTADOS_TERMINALES

ESTADOS_CAPTURABLES = {AUTORIZADO, CAPTURANDO}
ESTADOS_PAGADOS = {RETENIDO, LIBERADO}
ESTADOS_REEMBOLSABLES = {RETENIDO, LIBERADO}


class TransicionInvalida(ValueError):
    """Se intentó un cambio de estado no permitido por la máquina."""


def puede_transicionar(de_estado, a_estado):
    return a_estado in TRANSICIONES.get(de_estado, set())


def validar_transicion(de_estado, a_estado):
    if not puede_transicionar(de_estado, a_estado):
        raise TransicionInvalida(
            f"Transición de pago inválida: {de_estado} -> {a_estado}."
        )
