from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class MicrotechConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "microtech"
    verbose_name = _("Microtech")

    def ready(self) -> None:
        from microtech.signals import (
            ensure_swiss_customs_field_defaults,
            sync_order_rule_django_field_catalog,
        )

        post_migrate.connect(
            ensure_swiss_customs_field_defaults,
            sender=self,
            dispatch_uid="microtech.ensure_swiss_customs_field_defaults",
        )
        post_migrate.connect(
            sync_order_rule_django_field_catalog,
            sender=self,
            dispatch_uid="microtech.sync_order_rule_django_field_catalog",
        )
