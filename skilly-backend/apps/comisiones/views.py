"""
Vistas del panel de administración relacionadas con métricas.

El shell y las colas viven en sus apps (postulaciones, reservas, usuarios).
Acá se concentran los reportes que cruzan varias apps: resumen general y
comisiones. Son de solo lectura; la configuración de la tasa (TasaComision)
llega con la fase de comisiones.
"""
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalogo.models import Servicio
from apps.pagos import estados as pagos_estados
from apps.pagos.models import Pago
from apps.postulaciones.models import Postulacion
from apps.reservas.models import Disputa, EventoReserva, Reserva
from apps.usuarios.models import Organizacion
from apps.usuarios.permisos import EsAdmin

MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]

MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _rango_mes(anio, mes):
    tz = timezone.get_current_timezone()
    inicio = datetime(anio, mes, 1, tzinfo=tz)
    if mes == 12:
        fin = datetime(anio + 1, 1, 1, tzinfo=tz)
    else:
        fin = datetime(anio, mes + 1, 1, tzinfo=tz)
    return inicio, fin


def _mes_anterior(anio, mes, meses_atras=1):
    total = anio * 12 + (mes - 1) - meses_atras
    return total // 12, total % 12 + 1


def _mes_solicitado(request):
    valor = (request.query_params.get("mes") or "").strip()
    if not valor:
        hoy = timezone.localtime()
        return hoy.year, hoy.month
    try:
        anio_txt, mes_txt = valor.split("-")
        anio, mes = int(anio_txt), int(mes_txt)
        if not 1 <= mes <= 12:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValidationError({"mes": "Usa el formato YYYY-MM."})
    return anio, mes


def _pagos_liberados(anio, mes):
    inicio, fin = _rango_mes(anio, mes)
    return Pago.objects.filter(
        estado=pagos_estados.LIBERADO,
        liberado_en__gte=inicio,
        liberado_en__lt=fin,
    ).select_related(
        "reserva",
        "reserva__servicio",
        "reserva__servicio__categoria",
        "reserva__organizacion",
        "reserva__profesional",
    )


def _comision_mes(anio, mes):
    return _pagos_liberados(anio, mes).aggregate(total=Sum("monto_comision"))[
        "total"
    ] or 0


class AdminResumenView(APIView):
    """GET /api/admin/resumen/ — KPIs, servicios por categoría y actividad.

    Alimenta la primera pantalla del panel (ticket 5.7 y 5.8). La actividad
    combina EventoReserva (3.11), postulaciones y servicios en revisión, que
    son los tres hechos que el admin necesita ver primero.
    """

    permission_classes = [EsAdmin]

    def get(self, request):
        hoy = timezone.localtime()
        comision_mes = _comision_mes(hoy.year, hoy.month)

        servicios_activos = Servicio.objects.filter(
            estado=Servicio.ESTADO_APROBADO, activo=True
        )

        por_categoria = list(
            servicios_activos.values("categoria__nombre")
            .annotate(total=Count("id"))
            .order_by("-total")[:6]
        )

        actividad = []

        for evento in (
            EventoReserva.objects.select_related("reserva__servicio")
            .order_by("-creado_en")[:6]
        ):
            if evento.tipo == EventoReserva.TIPO_PROBLEMA:
                tipo = "alert"
            elif evento.tipo in (
                EventoReserva.TIPO_VENCIDA,
                EventoReserva.TIPO_RECHAZADA,
                EventoReserva.TIPO_CANCELADA,
            ):
                tipo = "warn"
            else:
                tipo = "ok"
            actividad.append(
                {
                    "tipo": tipo,
                    "texto": evento.get_tipo_display(),
                    "detalle": evento.reserva.servicio.titulo,
                    "fecha": evento.creado_en.isoformat(),
                }
            )

        for postulacion in (
            Postulacion.objects.filter(estado=Postulacion.ESTADO_PENDIENTE)
            .select_related("profesional")
            .order_by("-fecha_postulacion")[:6]
        ):
            actividad.append(
                {
                    "tipo": "warn",
                    "texto": "Nueva postulación recibida",
                    "detalle": (
                        f"{postulacion.profesional.nombre_completo} · "
                        f"{postulacion.especialidad or 'Sin especialidad'}"
                    ),
                    "fecha": postulacion.fecha_postulacion.isoformat(),
                }
            )

        for servicio in (
            Servicio.objects.filter(estado=Servicio.ESTADO_EN_REVISION)
            .select_related("profesional")
            .order_by("-fecha_ultima_actualizacion")[:6]
        ):
            actividad.append(
                {
                    "tipo": "warn",
                    "texto": "Servicio enviado a revisión",
                    "detalle": f"{servicio.titulo} · {servicio.profesional.nombre_completo}",
                    "fecha": servicio.fecha_ultima_actualizacion.isoformat(),
                }
            )

        actividad.sort(key=lambda item: item["fecha"], reverse=True)

        return Response(
            {
                "kpis": {
                    "postulaciones_pendientes": Postulacion.objects.filter(
                        estado=Postulacion.ESTADO_PENDIENTE
                    ).count(),
                    "servicios_activos": servicios_activos.count(),
                    "disputas_abiertas": Disputa.objects.filter(
                        estado__in=[Disputa.ESTADO_ABIERTA, Disputa.ESTADO_EN_REVISION]
                    ).count(),
                    "comision_mes": comision_mes,
                    "organizaciones_activas": Organizacion.objects.filter(
                        activa=True
                    ).count(),
                    "solicitudes_vencidas": Reserva.objects.filter(
                        estado=Reserva.ESTADO_VENCIDA
                    ).count(),
                },
                "servicios_por_categoria": [
                    {
                        "categoria": fila["categoria__nombre"] or "Sin categoría",
                        "total": fila["total"],
                    }
                    for fila in por_categoria
                ],
                "actividad": actividad[:8],
            }
        )


class AdminComisionesView(APIView):
    """GET /api/admin/comisiones/?mes=YYYY-MM

    Reporte mensual e histórico de comisiones. Se calcula desde los pagos
    liberados (snapshot de la tasa en `Pago.monto_comision`), así que cambiar
    la tasa en el futuro no altera meses ya cerrados.
    """

    permission_classes = [EsAdmin]

    def get(self, request):
        anio, mes = _mes_solicitado(request)

        pagos = _pagos_liberados(anio, mes)
        comision_mes = 0
        total_mes = 0
        por_categoria = defaultdict(lambda: {"monto": 0, "servicios": 0})
        detalle = []

        for pago in pagos:
            comision_mes += pago.monto_comision
            total_mes += pago.monto_total
            categoria = (
                pago.reserva.servicio.categoria.nombre
                if pago.reserva.servicio.categoria_id
                else "Sin categoría"
            )
            por_categoria[categoria]["monto"] += pago.monto_comision
            por_categoria[categoria]["servicios"] += 1
            detalle.append(
                {
                    "id": pago.id,
                    "servicio": pago.reserva.servicio.titulo,
                    "organizacion": pago.reserva.organizacion.nombre,
                    "profesional": pago.reserva.profesional.nombre_completo,
                    "monto_servicio": pago.monto_total,
                    "comision": pago.monto_comision,
                    "fecha_liberacion": (
                        pago.liberado_en.isoformat() if pago.liberado_en else None
                    ),
                }
            )

        comision_historica = (
            Pago.objects.filter(estado=pagos_estados.LIBERADO).aggregate(
                total=Sum("monto_comision")
            )["total"]
            or 0
        )

        anio_ant, mes_ant = _mes_anterior(anio, mes)
        comision_anterior = _comision_mes(anio_ant, mes_ant)
        variacion = None
        if comision_anterior:
            variacion = round(
                (comision_mes - comision_anterior) / comision_anterior * 100, 1
            )

        serie = []
        for atras in range(5, -1, -1):
            anio_item, mes_item = _mes_anterior(anio, mes, atras)
            serie.append(
                {
                    "mes": f"{anio_item:04d}-{mes_item:02d}",
                    "etiqueta": MESES_CORTOS[mes_item - 1],
                    "monto": _comision_mes(anio_item, mes_item),
                }
            )

        servicios_facturados = pagos.count()

        return Response(
            {
                "mes": f"{anio:04d}-{mes:02d}",
                "mes_etiqueta": f"{MESES[mes - 1]} {anio}",
                "tasa_vigente": float(
                    getattr(settings, "TASA_COMISION_DEFECTO", 0.10)
                ),
                "comision_mes": comision_mes,
                "comision_mes_anterior": comision_anterior,
                "variacion_pct": variacion,
                "comision_historica": comision_historica,
                "servicios_facturados": servicios_facturados,
                "total_mes": total_mes,
                "comision_promedio": (
                    round(comision_mes / servicios_facturados)
                    if servicios_facturados
                    else 0
                ),
                "serie_mensual": serie,
                "por_categoria": [
                    {"categoria": nombre, **valores}
                    for nombre, valores in sorted(
                        por_categoria.items(),
                        key=lambda item: item[1]["monto"],
                        reverse=True,
                    )
                ],
                "detalle": detalle,
            }
        )
