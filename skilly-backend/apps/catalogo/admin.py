from django.contrib import admin

from apps.catalogo.models import Categoria


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "slug", "aprobada", "activa")
    list_filter = ("aprobada", "activa")
    search_fields = ("nombre", "slug")
    prepopulated_fields = {"slug": ("nombre",)}
    ordering = ("nombre",)