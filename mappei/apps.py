import os
import sys

from django.apps import AppConfig


class MappeiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mappei"
    verbose_name = "Mappei"

    def ready(self) -> None:
        if _is_server_process():
            from mappei.services.scheduler import MappeiSchedulerWorker
            MappeiSchedulerWorker.get().start()


def _is_server_process() -> bool:
    """Return True only when running as a Django web server, not management commands."""
    if any("gunicorn" in arg for arg in sys.argv):
        return os.getenv("MAPPEI_SCHEDULER_IN_WEB", "").strip().lower() in {"1", "true", "yes", "on"}
    if any("uvicorn" in arg for arg in sys.argv):
        return True
    if len(sys.argv) >= 2 and sys.argv[1] == "runserver":
        return True
    return False
