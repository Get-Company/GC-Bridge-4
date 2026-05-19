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
