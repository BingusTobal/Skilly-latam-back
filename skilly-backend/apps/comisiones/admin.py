from django.contrib import admin

from .models import TasaComision


@admin.register(TasaComision)
class TasaComisionAdmin(admin.ModelAdmin):
    list_display = ("categoria", "tasa", "vigente_desde", "activa", "creada_por")
    list_filter = ("activa", "categoria")
    ordering = ("-vigente_desde", "-id")
    readonly_fields = ("creada_por", "creada_en")
