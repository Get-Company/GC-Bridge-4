from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase

from documents.document_version_service import DocumentVersionService
from documents.models import Document, DocumentVersion


class DocumentVersionServiceTests(TestCase):
    @patch("documents.document_version_service.DocumentShopwarePublicationService.publish")
    def test_activate_uses_snapshot_and_overwrites_shopware_media(
        self,
        mock_publish,
    ):
        document = Document.objects.create(
            slug="agb",
            title="AGB",
            html_content="<p>V1</p>",
            css_content="p { color: red; }",
            shopware_cms_page_id="cms-page-id",
            shopware_media_id="stable-media-id",
        )
        service = DocumentVersionService()
        first_version = service.create_from_document(document, label="Freigabe 1")
        document.html_content = "<p>V2</p>"
        document.css_content = "p { color: blue; }"
        document.save(update_fields=("html_content", "css_content", "updated_at"))
        second_version = service.create_from_document(document, label="Freigabe 2")
        mock_publish.return_value = {
            "cms_page_id": "cms-page-id",
            "cms_slot_id": "cms-slot-id",
            "media_id": "stable-media-id",
        }

        result = service.activate_and_publish(second_version)

        document.refresh_from_db()
        first_version.refresh_from_db()
        second_version.refresh_from_db()
        self.assertEqual(
            result,
            {
                "cms_page_id": "cms-page-id",
                "cms_slot_id": "cms-slot-id",
                "media_id": "stable-media-id",
            },
        )
        self.assertEqual(document.active_version_id, second_version.pk)
        self.assertEqual(document.html_content, "<p>V2</p>")
        self.assertEqual(document.css_content, "p { color: blue; }")
        self.assertFalse(first_version.is_active)
        self.assertTrue(second_version.is_active)
        mock_publish.assert_called_once_with(document)

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
