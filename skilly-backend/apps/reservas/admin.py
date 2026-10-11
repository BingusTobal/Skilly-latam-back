from django.contrib import admin

from apps.reservas.models import Disputa, EventoReserva, Reserva


class EventoReservaInline(admin.TabularInline):
    model = EventoReserva
    extra = 0
    readonly_fields = ("tipo", "actor", "detalle", "creado_en")
    ordering = ("creado_en",)
    can_delete = False


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "servicio",
        "organizacion",
        "profesional",
        "fecha",
        "hora_inicio",
        "estado",
        "precio_acordado",
    )
    list_filter = ("estado", "fecha", "formato")
    search_fields = (
        "servicio__titulo",
        "organizacion__nombre",
        "profesional__nombre_completo",
        "contacto_email",
    )
    readonly_fields = (
        "precio_acordado",
        "tasa_comision",
        "formato",
        "ubicacion",
        "token_hash",
        "token_expira",
        "expira_en",
        "creada_en",
        "actualizada_en",
        "aceptada_en",
        "entregado_en",
        "confirmada_en",
        "cancelada_en",
    )
    inlines = [EventoReservaInline]
    ordering = ("-creada_en",)


@admin.register(EventoReserva)
class EventoReservaAdmin(admin.ModelAdmin):
    list_display = ("reserva", "tipo", "actor", "creado_en")
    list_filter = ("tipo",)
    search_fields = ("reserva__servicio__titulo", "detalle")
    ordering = ("-creado_en",)


@admin.register(Disputa)
class DisputaAdmin(admin.ModelAdmin):
    list_display = ("reserva", "motivo", "estado", "creada_en")
    list_filter = ("estado",)
    search_fields = ("motivo", "descripcion", "reserva__servicio__titulo")
    ordering = ("-creada_en",)
