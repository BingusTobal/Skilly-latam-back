from django.apps import AppConfig


class ReservasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reservas"
    label = "reservas"
    verbose_name = "Reserva, su maquina de estados y el calculo de slots."
