from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai"
    verbose_name = _("Künstliche Intelligenz")

    def ready(self) -> None:
        from ai.signals import ensure_document_prompt_default

        post_migrate.connect(
            ensure_document_prompt_default,
            sender=self,
            dispatch_uid="ai.ensure_document_prompt_default",
        )
