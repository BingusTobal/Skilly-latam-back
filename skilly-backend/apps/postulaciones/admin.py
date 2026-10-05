"""
Admin de postulaciones. Decisión 2 del Sprint 1: el admin Django queda usable
para moderar en este repo, mientras el shell React del panel admin vive en el
frontend (otro repo).

Lo importante acá es que las dos moderaciones están separadas:

  - PostulacionAdmin tiene acciones aprobar / devolver / rechazar.
  - CertificadoAdmin tiene acciones aprobar / rechazar.

Aprobar la postulación NO toca los certificados y viceversa (R9).
"""
from django.contrib import admin, messages

from .models import Certificado, Postulacion


class CertificadoInline(admin.TabularInline):
    model = Certificado
    extra = 0
    fields = ("tipo", "nombre", "enlace", "estado", "comentario_revisor", "fecha_revision")
    readonly_fields = ("estado", "comentario_revisor", "fecha_revision", "revisado_por")


@admin.register(Postulacion)
class PostulacionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profesional",
        "estado",
        "especialidad",
        "fecha_postulacion",
        "fecha_revision",
    )
    list_filter = ("estado",)
    search_fields = (
        "profesional__nombre_completo",
        "profesional__rut",
        "profesional__usuario__email",
    )
    ordering = ("-fecha_postulacion",)
    autocomplete_fields = ("profesional", "revisada_por")
    readonly_fields = ("fecha_postulacion", "fecha_revision", "revisada_por")
    inlines = [CertificadoInline]
    actions = ("accion_aprobar", "accion_devolver", "accion_rechazar")

    fieldsets = (
        (None, {"fields": ("profesional", "estado", "especialidad", "experiencia")}),
        ("Revisión", {"fields": ("comentarios_admin", "revisada_por", "fecha_revision")}),
        ("Auditoría", {"fields": ("fecha_postulacion",)}),
    )

    def _aplicar(self, request, queryset, metodo, etiqueta):
        """Aplica la transición y avisa cuántos quedaron bien."""
        from apps.usuarios.correo import (
            enviar_postulacion_aprobada,
            enviar_postulacion_devuelta,
            enviar_postulacion_rechazada,
        )

        correos = {
            "aprobar": enviar_postulacion_aprobada,
            "devolver": enviar_postulacion_devuelta,
            "rechazar": enviar_postulacion_rechazada,
        }

        hechos = 0
        fallidos = []
        for postulacion in queryset:
            # El estado se fija acá para que `admin.site.save_model` no lo
            # revierta al guardar el formulario.
            if metodo != "aprobar" and not postulacion.comentarios_admin.strip():
                fallidos.append(f"#{postulacion.pk} (sin comentarios)")
                continue
            try:
                if metodo == "aprobar":
                    # `aprobar` no lleva comentarios: solo devolver y rechazar
                    # los necesitan.
                    postulacion.aprobar(request.user)
                else:
                    getattr(postulacion, metodo)(
                        request.user, postulacion.comentarios_admin
                    )
                correos[metodo](postulacion)
                hechos += 1
            except Exception as exc:  # noqa: BLE001
                fallidos.append(f"#{postulacion.pk} ({exc})")

        if hechos:
            self.message_user(
                request, f"{hechos} postulación(es) {etiqueta}.", messages.SUCCESS
            )
        if fallidos:
            self.message_user(
                request,
                "Sin aplicar: " + ", ".join(fallidos),
                messages.WARNING,
            )

    @admin.action(description="Aprobar postulaciones seleccionadas")
    def accion_aprobar(self, request, queryset):
        self._aplicar(request, queryset, "aprobar", "aprobadas")

    @admin.action(description="Devolver postulaciones para corrección")
    def accion_devolver(self, request, queryset):
        self._aplicar(request, queryset, "devolver", "devueltas")

    @admin.action(description="Rechazar postulaciones")
    def accion_rechazar(self, request, queryset):
        self._aplicar(request, queryset, "rechazar", "rechazadas")

    def save_model(self, request, obj, form, change):
        """Si el admin edita el estado a mano, deja registrado quién lo hizo."""
        super().save_model(request, obj, form, change)
        obj.revisada_por = request.user
        obj.fecha_revision = obj.fecha_revision or None
        obj.save(update_fields=["revisada_por"])


@admin.register(Certificado)
class CertificadoAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "tipo", "postulacion", "estado", "cargado_en")
    list_filter = ("tipo", "estado")
    search_fields = ("nombre", "postulacion__profesional__nombre_completo")
    ordering = ("-cargado_en",)
    autocomplete_fields = ("postulacion", "revisado_por")
    actions = ("accion_aprobar", "accion_rechazar")

    fieldsets = (
        (None, {"fields": ("postulacion", "tipo", "nombre", "archivo", "enlace")}),
        ("Revisión", {"fields": ("estado", "comentario_revisor", "revisado_por", "fecha_revision")}),
    )

    def get_readonly_fields(self, request, obj=None):
        # El perfil de LinkedIn no se puede moderar a mano: su estado lo define
        # la validación de formato de la URL, no un criterio del admin.
        if obj is not None and obj.estado == Certificado.ESTADO_VERIFICADO_AUTOMATICO:
            return ("estado",) + self.readonly_fields
        return self.readonly_fields

    def _aplicar_certificados(self, request, queryset, aprobar):
        from django.core.exceptions import ValidationError

        from apps.usuarios.correo import enviar_certificado_rechazado

        hechos = 0
        omitidos = 0
        for certificado in queryset:
            try:
                if aprobar:
                    certificado.aprobar(request.user)
                else:
                    certificado.rechazar(request.user, certificado.comentario_revisor)
                    enviar_certificado_rechazado(certificado)
                hechos += 1
            except ValidationError:
                # LinkedIn ya verificado: no entra a moderación.
                omitidos += 1

        if hechos:
            self.message_user(
                request,
                f"{hechos} certificado(s) "
                f"{'aprobados' if aprobar else 'rechazados'}.",
                messages.SUCCESS,
            )
        if omitidos:
            self.message_user(
                request,
                f"{omitidos} certificado(s) de LinkedIn omitidos: no requieren moderación.",
                messages.INFO,
            )

    @admin.action(description="Aprobar certificados seleccionados")
    def accion_aprobar(self, request, queryset):
        self._aplicar_certificados(request, queryset, aprobar=True)

    @admin.action(description="Rechazar certificados seleccionados")
    def accion_rechazar(self, request, queryset):
        self._aplicar_certificados(request, queryset, aprobar=False)