from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
    verbose_name = _("Dokumente")

    def ready(self) -> None:
        from documents.signals import ensure_document_type_defaults

        post_migrate.connect(
            ensure_document_type_defaults,
            sender=self,
            dispatch_uid="documents.ensure_document_type_defaults",
        )
