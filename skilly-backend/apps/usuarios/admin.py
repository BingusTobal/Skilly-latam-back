from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.usuarios.models import Usuario


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
