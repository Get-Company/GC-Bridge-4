from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from documents.models import Document
from documents.shopware_publication_service import DocumentShopwarePublicationService


class DocumentShopwarePublicationServiceTests(SimpleTestCase):
    def test_lists_publishable_layouts_and_pdf_media(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)
        service._search_all = MagicMock(
            side_effect=[
                [
                    {"id": "page-id", "name": "AGB", "type": "page"},
                    {"id": "landing-id", "name": "Newsletter", "type": "landingpage"},
                    {"id": "product-id", "name": "Produkt", "type": "product_list"},
                ],
                [
                    {"id": "pdf-id", "fileName": "agb", "fileExtension": "pdf"},
                ],
            ]
        )

        self.assertEqual(
            service.list_layout_choices(),
            [("page-id", "AGB (page)"), ("landing-id", "Newsletter (landingpage)")],
        )
        self.assertEqual(service.list_pdf_media_choices(), [("pdf-id", "agb.pdf")])

    def test_lists_media_folders_as_hierarchical_choices(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)
        service._search_all = MagicMock(
            return_value=[
                {"id": "root-id", "name": "Dokumente", "parentId": None},
                {"id": "legal-id", "name": "Rechtliches", "parentId": "root-id"},
            ]
        )

        self.assertEqual(
            service.list_media_folder_choices(),
            [("root-id", "Dokumente"), ("legal-id", "Dokumente / Rechtliches")],
        )

    def test_publish_regenerates_pdf_before_overwriting_selected_media(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)
        document = Document(
            title="AGB",
            html_content="<p>Aktueller Inhalt</p>",
            shopware_cms_page_id="page-id",
            shopware_media_id="media-id",
        )
        service._fetch_pdf_media = MagicMock()
        service.publish_layout = MagicMock(return_value="slot-id")
        publication_steps: list[str] = []

        with (
            patch("documents.shopware_publication_service.DocumentPdfService") as pdf_service_class,
            patch("documents.shopware_publication_service.DocumentShopwareUploadService") as upload_service_class,
        ):
            pdf_service = pdf_service_class.return_value
            pdf_service.render_document_html.return_value = "<p>Aktueller Inhalt</p>"
            pdf_service.generate_pdf.side_effect = lambda _: publication_steps.append("generate-pdf")
            service.publish_layout.side_effect = lambda *_args, **_kwargs: (
                publication_steps.append("update-layout") or "slot-id"
            )
            upload_service_class.return_value.upload_pdf.side_effect = lambda _: (
                publication_steps.append("upload-pdf") or "media-id"
            )

            result = service.publish(document)

        self.assertEqual(
            result,
            {"cms_page_id": "page-id", "cms_slot_id": "slot-id", "media_id": "media-id"},
        )
        service._fetch_pdf_media.assert_called_once_with("media-id")
        pdf_service.generate_pdf.assert_called_once_with(document)
        service.publish_layout.assert_called_once_with(document, rendered_html="<p>Aktueller Inhalt</p>")
        upload_service_class.return_value.upload_pdf.assert_called_once_with(document)
        self.assertEqual(publication_steps, ["generate-pdf", "update-layout", "upload-pdf"])

    def test_publish_requires_selected_shopware_pdf_media(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)

        with self.assertRaisesMessage(ValueError, "PDF-Datei auswählen"):
            service.publish(Document(title="AGB", shopware_cms_page_id="page-id"))

    def test_publish_overwrites_pdf_without_a_linked_layout(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)
        document = Document(title="AGB", shopware_media_id="media-id")
        service._fetch_pdf_media = MagicMock()
        service.publish_layout = MagicMock()
        publication_steps: list[str] = []

        with (
            patch("documents.shopware_publication_service.DocumentPdfService") as pdf_service_class,
            patch("documents.shopware_publication_service.DocumentShopwareUploadService") as upload_service_class,
        ):
            pdf_service = pdf_service_class.return_value
            pdf_service.generate_pdf.side_effect = lambda _: publication_steps.append("generate-pdf")
            upload_service_class.return_value.upload_pdf.side_effect = lambda _: (
                publication_steps.append("upload-pdf") or "media-id"
            )

            result = service.publish(document)

        self.assertEqual(
            result,
            {"cms_page_id": "", "cms_slot_id": "", "media_id": "media-id"},
        )
        service._fetch_pdf_media.assert_called_once_with("media-id")
        pdf_service.render_document_html.assert_not_called()
        pdf_service.generate_pdf.assert_called_once_with(document)
        service.publish_layout.assert_not_called()
        upload_service_class.return_value.upload_pdf.assert_called_once_with(document)
        self.assertEqual(publication_steps, ["generate-pdf", "upload-pdf"])

    def test_publish_rejects_a_missing_selected_pdf_media(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)
        service.request_post = MagicMock(return_value={"data": []})

        with self.assertRaisesMessage(ValueError, "PDF-Datei media-id wurde nicht gefunden"):
            service._fetch_pdf_media("media-id")

    def test_publish_rejects_a_missing_selected_media_folder(self):
        service = DocumentShopwarePublicationService.__new__(DocumentShopwarePublicationService)
        service.request_post = MagicMock(return_value={"data": []})

        with self.assertRaisesMessage(ValueError, "Medienordner folder-id wurde nicht gefunden"):
            service._fetch_media_folder("folder-id")
