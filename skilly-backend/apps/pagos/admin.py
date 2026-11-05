from django.contrib import admin

from .models import Pago, PagoEvento


class PagoEventoInline(admin.TabularInline):
    model = PagoEvento
    extra = 0
    can_delete = False
    readonly_fields = (
        "de_estado",
        "a_estado",
        "actor",
        "motivo",
        "datos",
        "creado_en",
    )
    ordering = ("creado_en", "id")


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = (
        "referencia_publica",
        "reserva",
        "estado",
        "pasarela",
        "monto_total",
        "monto_reembolsado",
        "creado_en",
    )
    list_filter = ("estado", "pasarela", "creado_en")
    search_fields = ("referencia_publica", "buy_order", "reserva__id")
    readonly_fields = (
        "referencia_publica",
        "reserva",
        "estado",
        "pasarela",
        "monto_total",
        "monto_comision",
        "monto_neto",
        "buy_order",
        "session_id",
        "token_corto",
        "url_pago",
        "codigo_autorizacion",
        "tipo_pago",
        "cuotas",
        "tarjeta_ultimos4",
        "codigo_respuesta",
        "capturado_en_autorizacion",
        "monto_reembolsado",
        "expira_en",
        "autorizado_en",
        "capturado_en",
        "liberado_en",
        "reembolsado_en",
        "cancelado_en",
        "respuesta_pasarela",
        "creado_en",
        "actualizado_en",
    )
    inlines = [PagoEventoInline]
    ordering = ("-creado_en",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PagoEvento)
class PagoEventoAdmin(admin.ModelAdmin):
    list_display = ("pago", "de_estado", "a_estado", "actor", "creado_en")
    list_filter = ("actor", "a_estado")
    search_fields = ("pago__referencia_publica", "pago__buy_order")
    readonly_fields = (
        "pago",
        "de_estado",
        "a_estado",
        "actor",
        "motivo",
        "datos",
        "creado_en",
    )
    ordering = ("-creado_en",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
