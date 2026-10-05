from django.apps import AppConfig


class PagosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pagos"
    label = "pagos"
    verbose_name = "Pago: autorizado, retenido, liberado o reembolsado."
