"""Vista de health check. Ticket 0.14.

Verifica que Django responde y que la base de datos esta conectada.
Devuelve 503 si la base no responde, para que un balanceador no mande trafico.
"""
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request):
    estado = {"servicio": "skilly-latam", "version": "1.0.0"}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        estado["base_datos"] = "ok"
        codigo = 200
    except Exception as exc:  # noqa: BLE001 - reportamos, no propagamos
        estado["base_datos"] = "error"
        estado["detalle"] = str(exc)
        codigo = 503

    return JsonResponse(estado, status=codigo)