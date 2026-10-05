"""Celery. Se activa en el Sprint 3 (ticket 3.13) para las tareas de expiracion."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("skilly")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
