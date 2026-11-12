"""Throttles del módulo de pagos.

Los límites concretos se configuran en `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`
con los scopes `pago_iniciar`, `pago_retorno` y `pago_estado`.
"""
from rest_framework.throttling import ScopedRateThrottle


class IniciarPagoThrottle(ScopedRateThrottle):
    scope = "pago_iniciar"


class RetornoPagoThrottle(ScopedRateThrottle):
    scope = "pago_retorno"


class EstadoPagoThrottle(ScopedRateThrottle):
    scope = "pago_estado"
