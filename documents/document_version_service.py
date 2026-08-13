from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.services import BaseService
from documents.models import Document, DocumentVersion
from documents.shopware_publication_service import DocumentShopwarePublicationService


class DocumentVersionService(BaseService):
    """Create and activate document snapshots through one controlled workflow."""

    model = DocumentVersion

    @transaction.atomic
    def create_from_document(self, document: Document, *, label: str = "") -> DocumentVersion:
        document = Document.objects.select_for_update().get(pk=document.pk)
        highest_version = document.versions.aggregate(highest=Max("version_number"))["highest"] or 0
        version_number = highest_version + 1
        return DocumentVersion.objects.create(
            document=document,
            version_number=version_number,
            label=label or f"Version {version_number}",
            template_source=document.get_template_source(),
            css_content=document.css_content,
            use_jinja2=document.use_jinja2,
        )

    @transaction.atomic
    def activate(self, version: DocumentVersion) -> Document:
        """Make one snapshot authoritative for its document without publishing it yet."""
        version = DocumentVersion.objects.select_for_update().select_related("document").get(pk=version.pk)
        document = Document.objects.select_for_update().get(pk=version.document_id)

        for current_version in document.versions.filter(is_active=True).exclude(pk=version.pk):
            current_version.is_active = False
            current_version.save(update_fields=("is_active", "updated_at"))

        version.is_active = True
        version.activated_at = timezone.now()
        version.save(update_fields=("is_active", "activated_at", "updated_at"))

        # A version always stores the resolved template text, even if its source
        # was originally uploaded as a file. Clearing the file prevents it from
        # taking precedence over the activated snapshot while rendering.
        document.active_version = version
        document.template_file = ""
        document.html_content = version.template_source
        document.css_content = version.css_content
        document.use_jinja2 = version.use_jinja2
        document.save(
            update_fields=(
                "active_version",
                "template_file",
                "html_content",
                "css_content",
                "use_jinja2",
                "updated_at",
            )
        )
        return document

    def activate_and_publish(self, version: DocumentVersion) -> dict[str, object]:
        # Do not activate a version if the document cannot be published at all
        # because its required Shopware PDF media has not been selected yet.
        DocumentShopwarePublicationService.validate_links(version.document)
        document = self.activate(version)
        return DocumentShopwarePublicationService().publish(document)
