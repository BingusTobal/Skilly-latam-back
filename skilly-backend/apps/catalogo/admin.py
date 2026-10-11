from django.contrib import admin

from apps.catalogo.models import Categoria, Entregable, RevisionServicio, Servicio


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "slug", "aprobada", "activa")
    list_filter = ("aprobada", "activa")
    search_fields = ("nombre", "slug")
    prepopulated_fields = {"slug": ("nombre",)}
    ordering = ("nombre",)


class EntregableInline(admin.TabularInline):
    model = Entregable
    extra = 1
    ordering = ("orden",)


@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = (
        "titulo",
        "profesional",
        "categoria",
        "estado",
        "precio",
        "formato",
        "activo",
        "fecha_creacion",
    )
    list_filter = ("estado", "formato", "activo", "categoria")
    search_fields = ("titulo", "slug", "profesional__nombre_completo")
    inlines = [EntregableInline]
    readonly_fields = (
        "slug",
        "fecha_creacion",
        "fecha_ultima_actualizacion",
        "fecha_publicacion",
        "fecha_revision",
        "revisado_por",
    )
    ordering = ("-fecha_creacion",)


@admin.register(Entregable)
class EntregableAdmin(admin.ModelAdmin):
    list_display = ("nombre", "servicio", "orden")
    search_fields = ("nombre", "servicio__titulo")
    ordering = ("servicio", "orden")


@admin.register(RevisionServicio)
class RevisionServicioAdmin(admin.ModelAdmin):
    list_display = ("servicio", "accion", "admin", "creado_en")
    list_filter = ("accion",)
    search_fields = ("servicio__titulo", "comentario")
    readonly_fields = ("servicio", "accion", "admin", "comentario", "creado_en")
    ordering = ("-creado_en",)