"""
Pruebas manuales contra Transbank integración.

No se ejecutan por defecto (`pytest.ini` excluye el marcador `sandbox`).
Ejecutar solo cuando haya credenciales de integración y red disponible:

    .venv/bin/pytest apps/pagos/tests/test_sandbox_transbank.py -m sandbox -q

El commit real requiere ingresar una tarjeta de prueba en el formulario de
Webpay; eso se valida manualmente y queda documentado en
`docs/PAGOS_TRANSBANK_VERIFICACION.md`.
"""
import uuid

import pytest

from apps.pagos.gateway.transbank import TransbankGateway


@pytest.mark.sandbox
def test_crear_y_consultar_transaccion_en_integracion(settings):
    if not settings.TRANSBANK_API_KEY_SECRET:
        pytest.skip("Falta TRANSBANK_API_KEY_SECRET de integración.")

    settings.TRANSBANK_ENV = "integration"
    settings.TRANSBANK_COMMERCE_CODE = "597055555540"
    gateway = TransbankGateway()

    sufijo = uuid.uuid4().hex[:10]
    resultado = gateway.crear(
        buy_order=f"SBX{sufijo}",
        session_id=f"sbx-{sufijo}",
        monto=1000,
        return_url=settings.TRANSBANK_RETURN_URL,
    )

    assert resultado.ok is True, resultado.error
    assert resultado.token
    assert resultado.url.startswith("https://webpay3gint.transbank.cl/")

    estado = gateway.estado(resultado.token)
    assert estado.ok is True
    assert estado.estado in {"INITIALIZED", "AUTHORIZED", "FAILED", "EXPIRED"}
