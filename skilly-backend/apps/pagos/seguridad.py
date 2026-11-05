"""
Utilidades de seguridad para el módulo de pagos.

Ningún número de tarjeta, CVV, token o secreto debe quedar en la bitácora ni
en `respuesta_pasarela`. `sanear()` se aplica a todo dato que venga de la
pasarela antes de guardarlo.
"""

CLAVES_SENSIBLES = {
    "api_key",
    "api_key_secret",
    "authorization",
    "card_number",
    "cvv",
    "numero_tarjeta",
    "secret",
    "tbk_token",
    "token",
    "token_ws",
}

MASCARA = "***"


def sanear(datos):
    """Devuelve una copia recursiva de `datos` sin claves sensibles."""
    if isinstance(datos, dict):
        return {
            clave: MASCARA if str(clave).lower() in CLAVES_SENSIBLES else sanear(valor)
            for clave, valor in datos.items()
        }
    if isinstance(datos, (list, tuple)):
        return [sanear(valor) for valor in datos]
    return datos


def token_corto(token):
    """Prefijo seguro para logs, nunca el token completo."""
    if not token:
        return ""
    return f"{token[:6]}…"
