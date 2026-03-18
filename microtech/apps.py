import sys

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class MicrotechConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "microtech"

    def ready(self) -> None:
        from microtech.signals import ensure_swiss_customs_field_defaults

        post_migrate.connect(
            ensure_swiss_customs_field_defaults,
            sender=self,
            dispatch_uid="microtech.ensure_swiss_customs_field_defaults",
        )

        # Only start queue worker in the main server process, not during
        # migrate, shell, makemigrations, collectstatic, or other commands.
        if _is_server_process():
            from microtech.services.queue_worker import MicrotechQueueWorker

            MicrotechQueueWorker.get().start()


def _is_server_process() -> bool:
    """Return True if we're running as uvicorn/runserver, not a management command."""
    # uvicorn: sys.argv[0] ends with "uvicorn"
    # runserver: "runserver" in sys.argv
    if any("uvicorn" in arg for arg in sys.argv):
        return True
    if len(sys.argv) >= 2 and sys.argv[1] == "runserver":
        return True
    return False
