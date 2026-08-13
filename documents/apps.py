from django.apps import AppConfig
from django.db.models.signals import post_migrate


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
    verbose_name = "Dokumente"

    def ready(self) -> None:
        from documents.signals import ensure_document_type_defaults

        post_migrate.connect(
            ensure_document_type_defaults,
            sender=self,
            dispatch_uid="documents.ensure_document_type_defaults",
        )
