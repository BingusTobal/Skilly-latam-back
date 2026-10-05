from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.usuarios.models import Horario, Organizacion, Profesional, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("email", "first_name", "last_name", "tipo", "is_admin", "is_active")
    list_filter = ("tipo", "is_admin", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    readonly_fields = ("last_login",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Nombre", {"fields": ("first_name", "last_name")}),
        ("Rol", {"fields": ("tipo", "is_admin", "is_active")}),
        ("Permisos", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "tipo", "is_admin"),
            },
        ),
    )


class HorarioInline(admin.TabularInline):
    model = Horario
    extra = 0
    fields = ("dia_semana", "hora_inicio", "hora_fin", "activo")


@admin.register(Organizacion)
class OrganizacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut", "email_contacto", "nombre_contacto", "modo", "activa")
    list_filter = ("modo", "activa")
    search_fields = ("nombre", "rut", "email_contacto", "nombre_contacto")
    ordering = ("nombre",)
    autocomplete_fields = ("usuario",)
    readonly_fields = ("creada_en",)

    fieldsets = (
        (None, {"fields": ("nombre", "giro", "nombre_contacto", "email_contacto", "telefono", "rut")}),
        ("Cuenta", {"fields": ("usuario", "modo", "activa")}),
        ("Auditoría", {"fields": ("creada_en",)}),
    )


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "rut", "email", "estado", "ciudad", "creado_en")
    list_filter = ("estado", "disponibilidad", "ciudad")
    search_fields = ("nombre_completo", "rut", "usuario__email")
    ordering = ("nombre_completo",)
    autocomplete_fields = ("usuario",)
    inlines = [HorarioInline]
    readonly_fields = ("creado_en", "fecha_estado")

    def email(self, obj):
        return obj.usuario.email

    email.short_description = "Email"
    email.admin_order_field = "usuario__email"

    fieldsets = (
        (None, {"fields": ("nombre_completo", "rut", "telefono", "ciudad", "bio")}),
        ("Cuenta", {"fields": ("usuario", "estado", "linkedin_url", "disponibilidad")}),
        ("Auditoría", {"fields": ("creado_en", "fecha_estado")}),
    )


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ("profesional", "dia_semana", "hora_inicio", "hora_fin", "activo")
    list_filter = ("dia_semana", "activo")
    search_fields = ("profesional__nombre_completo",)
    autocomplete_fields = ("profesional",)