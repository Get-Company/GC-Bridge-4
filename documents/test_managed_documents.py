"""Read-only checks for showing managed PDF sources in ordinary documents."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase

from documents.admin import DocumentAdmin
from documents.document_version_service import DocumentVersionService
from documents.models import Document, DocumentType
from documents.services import DocumentPdfService
from documents.shopware_publication_service import DocumentShopwarePublicationService


class ManagedDocumentTests(SimpleTestCase):
    @staticmethod
    def document_with_download(download):
        manager = Mock()
        manager.select_related.return_value.first.return_value = download
        manager.first.return_value = download
        return SimpleNamespace(pk=12, managed_downloads=manager, pdf_filename="")

    def test_download_type_is_available_for_ordinary_documents(self):
        self.assertIn(("download", "Download"), [(code, str(name)) for code, name in DocumentType.DEFAULT_DEFINITIONS])

    def test_document_pdf_path_uses_active_managed_version(self):
        output = SimpleNamespace(path="/tmp/documents/version-1.pdf")
        version = SimpleNamespace(output_file=output)
        document = self.document_with_download(SimpleNamespace(active_version=version))

        self.assertEqual(DocumentPdfService().get_pdf_path(document), Path(output.path))

    def test_document_admin_links_to_the_stored_pdf(self):
        document = self.document_with_download(SimpleNamespace(active_version=SimpleNamespace(version_number=1)))
        admin = DocumentAdmin(Document, AdminSite())
        with patch.object(DocumentPdfService, "get_pdf_path", return_value=Path(__file__)):
            link = admin.pdf_download_link(document)

        self.assertIn("PDF herunterladen", str(link))
        self.assertIn("/admin/documents/document/12/download-pdf/", str(link))

    @patch("documents.shopware_publication_service.ManagedDownloadService")
    def test_document_publication_uses_versioned_source(self, service_class):
        version = object()
        versions = Mock()
        versions.order_by.return_value.first.return_value = version
        document = self.document_with_download(SimpleNamespace(versions=versions))
        service_class.return_value.publish.return_value = {"media_id": "stable-media-id", "url": "https://example.com/a.pdf"}

        result = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService).publish(document)

        self.assertEqual(result["media_id"], "stable-media-id")
        service_class.return_value.publish.assert_called_once_with(version)

    def test_reviewed_html_version_becomes_a_new_managed_pdf_version(self):
        managed = SimpleNamespace(pk=7, is_active=True, versions=Mock())
        managed.versions.filter.return_value.first.return_value = None
        managed.versions.aggregate.return_value = {"value": 1}
        document = self.document_with_download(managed)
        document.shopware_media_id = "stable-media-id"
        version = SimpleNamespace(document=document, label="Geprüfte HTML-Version", version_number=2)
        service = DocumentVersionService()
        service.activate = Mock(return_value=document)
        created_version = object()

        with patch("documents.document_version_service.DocumentShopwarePublicationService.validate_links"):
            with patch("documents.document_version_service.transaction.atomic"):
                with patch("documents.document_version_service.ManagedDownload.objects.select_for_update") as locked:
                    with patch("documents.document_version_service.ManagedDownloadVersion.objects.create", return_value=created_version) as create:
                        with patch("documents.document_version_service.ManagedDownloadService") as publisher:
                            locked.return_value.get.return_value = managed
                            publisher.return_value.publish.return_value = {"media_id": "stable-media-id"}
                            result = service.activate_and_publish(version)

        create.assert_called_once_with(
            download=managed,
            version_number=2,
            label="Geprüfte HTML-Version",
            source_document_version=version,
        )
        publisher.return_value.publish.assert_called_once_with(created_version)
        self.assertEqual(result["media_id"], "stable-media-id")
