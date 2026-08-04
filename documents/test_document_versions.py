from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase

from documents.document_version_service import DocumentVersionService
from documents.models import Document, DocumentVersion


class DocumentVersionServiceTests(TestCase):
    @patch("documents.document_version_service.DocumentShopwareUploadService.upload_pdf")
    @patch("documents.document_version_service.DocumentPdfService.generate_pdf")
    def test_activate_uses_snapshot_and_overwrites_shopware_media(
        self,
        mock_generate_pdf,
        mock_upload_pdf,
    ):
        document = Document.objects.create(
            slug="agb",
            title="AGB",
            html_content="<p>V1</p>",
            css_content="p { color: red; }",
        )
        service = DocumentVersionService()
        first_version = service.create_from_document(document, label="Freigabe 1")
        document.html_content = "<p>V2</p>"
        document.css_content = "p { color: blue; }"
        document.save(update_fields=("html_content", "css_content", "updated_at"))
        second_version = service.create_from_document(document, label="Freigabe 2")
        mock_upload_pdf.return_value = "stable-media-id"

        result = service.activate_and_publish(second_version)

        document.refresh_from_db()
        first_version.refresh_from_db()
        second_version.refresh_from_db()
        self.assertEqual(result, {"media_id": "stable-media-id"})
        self.assertEqual(document.active_version_id, second_version.pk)
        self.assertEqual(document.html_content, "<p>V2</p>")
        self.assertEqual(document.css_content, "p { color: blue; }")
        self.assertFalse(first_version.is_active)
        self.assertTrue(second_version.is_active)
        mock_generate_pdf.assert_called_once()
        mock_upload_pdf.assert_called_once()

    def test_only_one_active_version_is_allowed_per_document(self):
        document = Document.objects.create(slug="datenschutz", title="Datenschutz")
        first_version = DocumentVersion.objects.create(
            document=document,
            version_number=1,
            template_source="<p>V1</p>",
            is_active=True,
        )
        second_version = DocumentVersion.objects.create(
            document=document,
            version_number=2,
            template_source="<p>V2</p>",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentVersion.objects.filter(pk=second_version.pk).update(is_active=True)

        first_version.refresh_from_db()
        self.assertTrue(first_version.is_active)
