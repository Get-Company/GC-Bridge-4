import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "GC_Bridge_4.settings")

app = Celery("GC_Bridge_4")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
