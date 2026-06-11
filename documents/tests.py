import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from django.contrib.admin.sites import AdminSite
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from documents.admin import DocumentAdmin
from documents.jinja2_env import price_list_catalog_sections
from documents.models import Document
from documents.shopware_upload_service import DocumentShopwareUploadService
from documents.services import DocumentPdfService
from products.models import Category, Price, Product, ProductProperty, PropertyGroup, PropertyValue


class DocumentRenderingTest(SimpleTestCase):
    def test_document_render_uses_saved_css_over_context_css(self):
        document = Document(
            title="Bestellschein",
            html_content="<style>{{ css }}</style><p>{{ title }}</p>",
            css_content="body { color: #111; }",
        )

        rendered = document.render({"title": "Juni", "css": "body { color: red; }"})

        self.assertIn("body { color: #111; }", rendered)
        self.assertNotIn("body { color: red; }", rendered)
        self.assertIn("<p>Juni</p>", rendered)

    def test_document_render_prefers_uploaded_template_file(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            document = Document(
                title="Bestellschein",
                html_content="<p>Fallback</p>",
                css_content="body { color: #111; }",
            )
            document.template_file.save(
                "bestellschein.html",
                ContentFile(b"<style>{{ css }}</style><h1>{{ document.title }}</h1>"),
                save=False,
            )

            rendered = document.render()

            self.assertIn("body { color: #111; }", rendered)
            self.assertIn("<h1>Bestellschein</h1>", rendered)
            self.assertNotIn("Fallback", rendered)

    def test_document_admin_exposes_template_reference(self):
        admin_instance = DocumentAdmin(Document, AdminSite())
        help_html = admin_instance.template_help()

        self.assertIn("Jinja2", help_html)
        self.assertIn("price_list_catalog_sections()", help_html)
        self.assertIn("category_sections", help_html)
        self.assertIn("row.price_display", help_html)
        self.assertIn("{{ document.title }}", help_html)
        self.assertIn("documents_document", help_html)
        self.assertIn("document_type", help_html)
        self.assertNotIn("Live-Vorschau", help_html)

        media = str(admin_instance.media)
        self.assertIn("documents/admin/document_editor.css", media)
        self.assertIn("documents/admin/document_editor.js", media)
        self.assertNotIn("template_preview_link", admin_instance.readonly_fields)
        self.assertNotIn("live_preview_button", admin_instance.readonly_fields)
        self.assertEqual(admin_instance.actions_detail[0]["items"], ["generate_pdf_detail", "preview_template_detail"])


class DocumentPriceListCatalogSectionsTest(TestCase):
    def test_price_list_catalog_sections_prefetches_rows_and_formats_missing_values(self):
        root = Category.objects.create(name="Ordner", slug="ordner", sort_order=10)
        child = Category.objects.create(name="Hebelordner", slug="hebelordner", parent=root, sort_order=20)
        product = Product.objects.create(erp_nr="A-1000", name="", unit="", factor=None)
        product.categories.add(child)

        sections = price_list_catalog_sections(root_level=0)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["name"], "Ordner")
        self.assertEqual(sections[0]["groups"][0]["name"], "Hebelordner")
        row = sections[0]["groups"][0]["rows"][0]
        self.assertEqual(row["erp_nr"], "A-1000")
        self.assertEqual(row["name"], "Ohne Bezeichnung")
        self.assertEqual(row["attributes"], [])
        self.assertEqual(row["vpe_display"], "-")
        self.assertEqual(row["price_display"], "-")
        self.assertEqual(row["rebate_quantity_display"], "-")
        self.assertEqual(row["rebate_price_display"], "-")

    def test_price_list_catalog_sections_includes_price_and_attributes(self):
        root = Category.objects.create(name="Papier", slug="papier", sort_order=10)
        product = Product.objects.create(erp_nr="A-2000", name="Kopierpapier", unit="Pack", factor=5)
        product.categories.add(root)
        group = PropertyGroup.objects.create(name="Farbe")
        value = PropertyValue.objects.create(group=group, name="Weiss")
        ProductProperty.objects.create(product=product, value=value)
        Price.objects.create(product=product, price="12.50", rebate_quantity=10, rebate_price="11.00")

        sections = price_list_catalog_sections(root_level=0)

        row = sections[0]["direct_rows"][0]
        self.assertEqual(row["attributes"], [{"group": "Farbe", "value": "Weiss"}])
        self.assertEqual(row["vpe_display"], "5 Pack")
        self.assertEqual(row["price_display"], "12,50 EUR")
        self.assertEqual(row["rebate_quantity_display"], "10")
        self.assertEqual(row["rebate_price_display"], "11,00 EUR")


class DocumentPdfServiceTest(SimpleTestCase):
    def test_build_pdf_filename_uses_slug(self):
        document = Document(slug="datenschutz", title="Datenschutzerklaerung")

        self.assertEqual(DocumentPdfService().build_pdf_filename(document), "datenschutz.pdf")

    @override_settings(DOCUMENT_PDF_ROOT="/tmp/gc-bridge-documents-test")
    def test_get_output_dir_uses_document_pdf_root_setting(self):
        self.assertEqual(str(DocumentPdfService().get_output_dir()), "/tmp/gc-bridge-documents-test")

    def test_build_pdf_html_wraps_fragments_with_css(self):
        document = Document(
            title="AGB",
            html_content="<h1>{{ document.title }}</h1>",
            css_content="body { font-family: sans-serif; }",
        )

        html = DocumentPdfService().build_pdf_html(document)

        self.assertIn("<!doctype html>", html)
        self.assertIn("<h1>AGB</h1>", html)
        self.assertIn("body { font-family: sans-serif; }", html)

    def test_render_allows_css_context_override(self):
        document = Document(
            title="Preisliste",
            html_content="<style>{{ css }}</style>",
        )

        html = document.render({"css": "body { font-family: Arial; }"})

        self.assertIn("font-family: Arial", html)

    def test_build_pdf_html_uses_default_price_list_css_when_empty(self):
        document = Document(
            slug=Document.Slug.PRICE_LIST,
            title="Preisliste",
            html_content="<html><head><style>{{ css }}</style></head><body></body></html>",
            css_content="",
        )

        html = DocumentPdfService().build_pdf_html(document)

        self.assertIn("font-family: Arial, Helvetica, sans-serif", html)


class DocumentShopwareUploadServiceTest(SimpleTestCase):
    def test_upload_pdf_reuses_existing_shopware_media_id(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(DOCUMENT_PDF_ROOT=tmpdir):
            Path(tmpdir, "agb.pdf").write_bytes(b"%PDF-1.4")
            document = Document(
                slug="agb",
                title="AGB",
                pdf_filename="agb.pdf",
                shopware_media_id="existing-media-id",
            )
            document.save = MagicMock()
            service = DocumentShopwareUploadService.__new__(DocumentShopwareUploadService)
            service.access_token = "token"
            service.request = MagicMock()
            service.delete_conflicting_media_by_filename = MagicMock(return_value=0)
            service._upload_pdf_file = MagicMock()

            media_id = DocumentShopwareUploadService.upload_pdf(service, document)

            self.assertEqual(media_id, "existing-media-id")
            service.request.assert_called_once_with(
                "POST",
                "/media",
                payload={
                    "id": "existing-media-id",
                    "mediaFolderId": "d6460afa064f4c8196ed5bd0f6ccbcb5",
                },
            )
            service.delete_conflicting_media_by_filename.assert_called_once_with(
                file_name="agb",
                extension="pdf",
                exclude_media_id="existing-media-id",
            )
            service._upload_pdf_file.assert_called_once()
            document.save.assert_called_once_with(update_fields=["shopware_media_id", "updated_at"])

    def test_upload_pdf_retries_after_duplicate_filename_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(DOCUMENT_PDF_ROOT=tmpdir):
            Path(tmpdir, "agb.pdf").write_bytes(b"%PDF-1.4")
            document = Document(slug="agb", title="AGB", pdf_filename="agb.pdf")
            document.save = MagicMock()
            service = DocumentShopwareUploadService.__new__(DocumentShopwareUploadService)
            service.access_token = "token"
            service.request = MagicMock()
            service.delete_conflicting_media_by_filename = MagicMock(return_value=1)
            service._upload_pdf_file = MagicMock(
                side_effect=[
                    RuntimeError("Shopware Media-Upload fehlgeschlagen (400): CONTENT__MEDIA_DUPLICATED_FILE_NAME"),
                    None,
                ]
            )

            media_id = DocumentShopwareUploadService.upload_pdf(service, document)

            self.assertEqual(media_id, DocumentShopwareUploadService.build_media_id(document))
            self.assertEqual(service.delete_conflicting_media_by_filename.call_count, 2)
            self.assertEqual(service._upload_pdf_file.call_count, 2)
