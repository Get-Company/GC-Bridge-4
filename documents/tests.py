import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django import forms
from django.contrib.admin.sites import AdminSite
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from pypdf import PdfReader, PdfWriter
from weasyprint import HTML as WeasyHTML

from documents.admin import DocumentAdmin, DocumentAdminForm
from documents.jinja2_env import price_list_catalog_sections
from documents.management.commands.init_documents import Command as InitDocumentsCommand
from documents.models import Document
from documents.shopware_upload_service import DocumentShopwareUploadService
from documents.services import DocumentPdfService
from unfold.contrib.forms.widgets import WysiwygWidget
from products.models import (
    Category,
    Price,
    Product,
    ProductProperty,
    ProductVariantAttribute,
    ProductVariantFamily,
    PropertyGroup,
    PropertyValue,
)


class DocumentRenderingTest(SimpleTestCase):
    def test_document_admin_uses_wysiwyg_for_html_content(self):
        form = DocumentAdminForm()

        self.assertIsInstance(form.fields["html_content"].widget, WysiwygWidget)

    def test_document_admin_uses_selects_for_shopware_links(self):
        form_class = type(
            "ShopwareLinkedDocumentAdminForm",
            (DocumentAdminForm,),
            {
                "shopware_layout_choices": [("layout-id", "AGB (page)")],
                "shopware_pdf_choices": [("media-id", "agb.pdf")],
            },
        )

        form = form_class(instance=Document(shopware_cms_page_id="layout-id", shopware_media_id="media-id"))

        self.assertIsInstance(form.fields["shopware_cms_page_id"], forms.ChoiceField)
        self.assertIsInstance(form.fields["shopware_media_id"], forms.ChoiceField)
        self.assertIn(("layout-id", "AGB (page)"), list(form.fields["shopware_cms_page_id"].choices))
        self.assertIn(("media-id", "agb.pdf"), list(form.fields["shopware_media_id"].choices))

    def test_document_editor_keeps_toolbar_visible_while_html_scrolls(self):
        stylesheet = Path("documents/static/documents/admin/document_editor.css").read_text(encoding="utf-8")
        script = Path("documents/static/documents/admin/document_editor.js").read_text(encoding="utf-8")

        self.assertIn(".document-editor-shell trix-toolbar", stylesheet)
        self.assertIn("overflow-y: auto;", stylesheet)
        self.assertIn("height: calc(100vh - 12rem);", stylesheet)
        self.assertIn("is-document-source-mode", stylesheet)
        self.assertIn("HTML-Code", script)
        self.assertIn("editor.editor.loadHTML", script)

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
        self.assertEqual(
            admin_instance.actions_detail[0]["items"],
            [
                "create_version_detail",
                "generate_pdf_detail",
                "publish_to_shopware_detail",
                "preview_template_detail",
            ],
        )

    def test_document_admin_marks_missing_shopware_links_as_not_publishable(self):
        admin_instance = DocumentAdmin(Document, AdminSite())

        self.assertIn("Nicht veröffentlichbar", str(admin_instance.shopware_link_ids(Document())))

    def test_duplicate_categories_are_only_shown_for_price_lists(self):
        admin_instance = DocumentAdmin(Document, AdminSite())

        self.assertEqual(
            admin_instance.conditional_fields["price_list_duplicate_categories"],
            "document_type == 'price_list'",
        )
        self.assertIn("price_list_duplicate_categories", admin_instance.autocomplete_fields)


class DocumentInitializationCommandTest(SimpleTestCase):
    def test_price_list_initialization_uses_jinja2_template_engine(self):
        command = InitDocumentsCommand()
        command._upsert = MagicMock()

        command._init_price_list(Document, force=True)

        args, _ = command._upsert.call_args
        defaults = args[2]
        self.assertTrue(defaults["use_jinja2"])
        self.assertEqual(
            defaults["html_content"],
            Path("documents/templates/preisliste.html").read_text(encoding="utf-8"),
        )
        self.assertIn("price_list_catalog_sections()", defaults["html_content"])

    def test_django_document_template_supports_comment_tag(self):
        document = Document(
            use_jinja2=False,
            html_content="{% comment %}Vorlagenhinweis{% endcomment %}<p>Preisliste</p>",
        )

        self.assertEqual(document.render(), "<p>Preisliste</p>")


class DocumentPriceListTemplateTest(SimpleTestCase):
    def test_repeats_main_and_subcategory_in_table_header_after_page_break(self):
        from documents.jinja2_env import build_env

        rows = [
            {
                "erp_nr": f"A-{index:04d}",
                "attributes": [{"group": "Farbe", "value": "Hellgelb"}],
                "vpe_display": "10",
                "price_display": "12,50 €",
                "rebate_quantity_display": "100",
                "rebate_price_display": "11,00 €",
            }
            for index in range(120)
        ]
        environment = build_env()
        environment.globals["price_list_catalog_sections"] = lambda: [
            {
                "name": "Orga-Mappen",
                "direct_rows": [],
                "groups": [{"name": "Standard-Mappen", "rows": rows}],
            }
        ]
        template_source = DocumentPdfService().get_default_price_list_template_source()
        rendered_html = environment.from_string(template_source).render()

        pdf = PdfReader(BytesIO(WeasyHTML(string=rendered_html).write_pdf()))

        self.assertGreater(len(pdf.pages), 1)
        second_page_text = pdf.pages[1].extract_text()
        self.assertIn("Orga-Mappen", second_page_text)
        self.assertIn("Standard-Mappen", second_page_text)


class DocumentPriceListCatalogSectionsTest(TestCase):
    def setUp(self):
        from shopware.models import ShopwareSettings

        self.default_channel = ShopwareSettings.objects.create(
            name="Standard",
            is_active=True,
            is_default=True,
        )

    def test_price_list_catalog_sections_omits_technical_root_and_groups_levels_two_and_three(self):
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz", sort_order=10)
        section = Category.objects.create(name="Ordner", slug="ordner", parent=root, sort_order=20)
        group = Category.objects.create(name="Hebelordner", slug="hebelordner", parent=section, sort_order=30)
        product = Product.objects.create(erp_nr="A-1000", name="", unit="", factor=None)
        product.categories.add(group)
        Price.objects.create(product=product, sales_channel=self.default_channel, price="10.00")

        sections = price_list_catalog_sections()

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
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-2", sort_order=10)
        section = Category.objects.create(name="Papier", slug="papier", parent=root, sort_order=20)
        group_category = Category.objects.create(
            name="Kopierpapier",
            slug="kopierpapier",
            parent=section,
            sort_order=30,
        )
        product = Product.objects.create(erp_nr="A-2000", name="Kopierpapier", unit="Pack", factor=5)
        product.categories.add(group_category)
        group = PropertyGroup.objects.create(name="Farbe")
        value = PropertyValue.objects.create(group=group, name="Weiss")
        ProductProperty.objects.create(product=product, value=value)
        Price.objects.create(
            product=product,
            sales_channel=self.default_channel,
            price="12.50",
            rebate_quantity=10,
            rebate_price="11.00",
        )

        sections = price_list_catalog_sections()

        row = sections[0]["groups"][0]["rows"][0]
        self.assertEqual(row["attributes"], [{"group": "Farbe", "value": "Weiss"}])
        self.assertEqual(row["vpe_display"], "5 Pack")
        self.assertEqual(row["price_display"], "12,50 €")
        self.assertEqual(row["rebate_quantity_display"], "10")
        self.assertEqual(row["rebate_price_display"], "11,00 €")

    def test_price_list_catalog_sections_excludes_prices_from_non_default_channels(self):
        from shopware.models import ShopwareSettings

        other_channel = ShopwareSettings.objects.create(name="B2B", is_active=True)
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-3")
        section = Category.objects.create(name="Papier", slug="papier-3", parent=root)
        group = Category.objects.create(name="Karton", slug="karton", parent=section)
        product = Product.objects.create(erp_nr="A-3000", name="Nur B2B")
        product.categories.add(group)
        Price.objects.create(product=product, sales_channel=other_channel, price="9.90")

        self.assertEqual(price_list_catalog_sections(), [])

    def test_price_list_catalog_sections_omits_level_two_products_and_deduplicates_products(self):
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-5")
        section = Category.objects.create(name="Ordner", slug="ordner-5", parent=root, sort_order=10)
        first_group = Category.objects.create(
            name="Hebelordner",
            slug="hebelordner-5",
            parent=section,
            sort_order=10,
        )
        second_group = Category.objects.create(
            name="Ringordner",
            slug="ringordner-5",
            parent=section,
            sort_order=20,
        )
        direct_product = Product.objects.create(erp_nr="A-5000", name="Nur Ebene 2")
        direct_product.categories.add(section)
        Price.objects.create(product=direct_product, sales_channel=self.default_channel, price="8.00")
        duplicate_product = Product.objects.create(erp_nr="A-6000", name="Mehrfach kategorisiert")
        duplicate_product.categories.add(first_group, second_group)
        Price.objects.create(product=duplicate_product, sales_channel=self.default_channel, price="9.00")

        sections = price_list_catalog_sections()

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["direct_rows"], [])
        self.assertEqual(len(sections[0]["groups"]), 1)
        self.assertEqual(sections[0]["groups"][0]["name"], "Hebelordner")
        self.assertEqual(
            [row["erp_nr"] for row in sections[0]["groups"][0]["rows"]],
            ["A-6000"],
        )

    def test_price_list_catalog_sections_skips_inactive_categories_but_uses_active_assignments(self):
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-6")
        section = Category.objects.create(name="Ordner", slug="ordner-6", parent=root, sort_order=10)
        active_group = Category.objects.create(
            name="Hebelordner",
            slug="hebelordner-6",
            parent=section,
            sort_order=10,
        )
        inactive_group = Category.objects.create(
            name="Archiv",
            slug="archiv-6",
            parent=section,
            is_active=False,
            sort_order=20,
        )
        Category.objects.create(
            name="Leere Unterkategorie",
            slug="leere-unterkategorie-6",
            parent=section,
            sort_order=30,
        )
        Category.objects.create(
            name="Leere Hauptkategorie",
            slug="leere-hauptkategorie-6",
            parent=root,
            sort_order=40,
        )
        inactive_section = Category.objects.create(
            name="Inaktive Hauptkategorie",
            slug="inaktive-hauptkategorie-6",
            parent=root,
            is_active=False,
            sort_order=50,
        )
        child_of_inactive_section = Category.objects.create(
            name="Unterkategorie",
            slug="unterkategorie-6",
            parent=inactive_section,
        )
        inactive_only_product = Product.objects.create(erp_nr="A-7000", name="Nur inaktiv")
        inactive_only_product.categories.add(inactive_group)
        Price.objects.create(product=inactive_only_product, sales_channel=self.default_channel, price="7.00")
        active_and_inactive_product = Product.objects.create(erp_nr="A-8000", name="Aktiv und inaktiv")
        active_and_inactive_product.categories.add(inactive_group, active_group)
        Price.objects.create(product=active_and_inactive_product, sales_channel=self.default_channel, price="8.00")
        hidden_section_product = Product.objects.create(erp_nr="A-9000", name="Inaktive Hauptkategorie")
        hidden_section_product.categories.add(child_of_inactive_section)
        Price.objects.create(product=hidden_section_product, sales_channel=self.default_channel, price="9.00")

        sections = price_list_catalog_sections()

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["name"], "Ordner")
        self.assertEqual(sections[0]["groups"][0]["name"], "Hebelordner")
        self.assertEqual(
            [row["erp_nr"] for row in sections[0]["groups"][0]["rows"]],
            ["A-8000"],
        )

    def test_price_list_catalog_sections_includes_deeper_category_names_in_the_group(self):
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-4")
        section = Category.objects.create(name="Mappen", slug="mappen", parent=root)
        group = Category.objects.create(name="Ringmappen", slug="ringmappen", parent=section)
        deep_category = Category.objects.create(name="A4", slug="a4", parent=group)
        product = Product.objects.create(erp_nr="A-4000", name="A4 Ringmappe")
        product.categories.add(group, deep_category)
        Price.objects.create(product=product, sales_channel=self.default_channel, price="7.50")

        sections = price_list_catalog_sections()

        self.assertEqual(sections[0]["name"], "Mappen")
        self.assertEqual(sections[0]["groups"][0]["name"], "Ringmappen - A4")
        self.assertEqual([row["erp_nr"] for row in sections[0]["groups"][0]["rows"]], ["A-4000"])

    def test_price_list_catalog_sections_allows_selected_category_subtree_to_repeat_products(self):
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-duplicates")
        standard_section = Category.objects.create(
            name="Buero", slug="buero-duplicates", parent=root, sort_order=10
        )
        standard_group = Category.objects.create(
            name="Ordner", slug="ordner-duplicates", parent=standard_section, sort_order=10
        )
        duplicate_section = Category.objects.create(
            name="Recycling", slug="recycling-duplicates", parent=root, sort_order=20
        )
        duplicate_group = Category.objects.create(
            name="Recycling-Ordner", slug="recycling-ordner-duplicates", parent=duplicate_section
        )
        product = Product.objects.create(erp_nr="A-10000", name="Recycling-Ordner")
        product.categories.add(standard_group, duplicate_group)
        Price.objects.create(product=product, sales_channel=self.default_channel, price="10.00")
        document = Document.objects.create(
            document_type=Document.DocumentType.PRICE_LIST,
            slug="preisliste-duplicates",
            title="Preisliste",
        )
        document.price_list_duplicate_categories.add(duplicate_section)

        sections = price_list_catalog_sections(document=document)

        rows_by_group = {
            group["name"]: [row["erp_nr"] for row in group["rows"]]
            for section in sections
            for group in section["groups"]
        }
        self.assertEqual(rows_by_group, {"Ordner": ["A-10000"], "Recycling-Ordner": ["A-10000"]})

    def test_price_list_catalog_sections_groups_variants_by_displayed_price_values(self):
        root = Category.objects.create(name="Deutsch/Schweiz", slug="deutsch-schweiz-variants")
        section = Category.objects.create(name="Organisation", slug="organisation-variants", parent=root)
        group_category = Category.objects.create(
            name="Register", slug="register-variants", parent=section
        )
        size_group = PropertyGroup.objects.create(name="Groesse")
        colour_group = PropertyGroup.objects.create(name="Farbe")
        size_six = PropertyValue.objects.create(group=size_group, name="6 cm")
        size_three = PropertyValue.objects.create(group=size_group, name="3 cm")
        white = PropertyValue.objects.create(group=colour_group, name="Weiss")
        yellow = PropertyValue.objects.create(group=colour_group, name="Gelb")
        standard_product = Product.objects.create(erp_nr="581000", name="Register 6 cm weiss")
        yellow_product = Product.objects.create(erp_nr="581001", name="Register 6 cm gelb")
        small_product = Product.objects.create(erp_nr="291000", name="Register 3 cm weiss")
        for product, values in (
            (standard_product, (size_six, white)),
            (yellow_product, (size_six, yellow)),
            (small_product, (size_three, white)),
        ):
            product.categories.add(group_category)
            Price.objects.create(
                product=product,
                sales_channel=self.default_channel,
                price="12.00" if product == small_product else "10.00",
            )
            for value in values:
                ProductProperty.objects.create(product=product, value=value)
        family = ProductVariantFamily.objects.create(
            slug="register-variants",
            name="Register",
            shopware_product_number="PARENT-REGISTER",
            target_category=group_category,
            default_product=standard_product,
        )
        family.source_categories.add(group_category)
        ProductVariantAttribute.objects.create(family=family, property_group=size_group, position=10)
        ProductVariantAttribute.objects.create(family=family, property_group=colour_group, position=20)

        sections = price_list_catalog_sections()

        rows = sections[0]["groups"][0]["rows"]
        self.assertEqual([row["erp_nr"] for row in rows], ["291000", "581000"])
        self.assertEqual(
            rows[0]["attributes"],
            [{"group": "Groesse", "value": "3 cm"}, {"group": "Farbe", "value": "Weiss"}],
        )
        self.assertEqual(
            rows[1]["attributes"],
            [{"group": "Groesse", "value": "6 cm"}, {"group": "Farbe", "value": "Weiss - Gelb"}],
        )


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
            document_type=Document.DocumentType.PRICE_LIST,
            slug="individuelle-preisliste",
            title="Preisliste",
            html_content="<html><head><style>{{ css }}</style></head><body></body></html>",
            css_content="",
        )

        html = DocumentPdfService().build_pdf_html(document)

        self.assertIn("font-family: Arial, Arimo", html)

    def test_legacy_price_increase_template_uses_customer_price_list_template(self):
        document = Document(
            document_type=Document.DocumentType.PRICE_LIST,
            title="Preisliste",
            html_content='<section data-pdf-section="cover">{{ price_increase.title }}</section>',
        )

        self.assertTrue(DocumentPdfService().should_use_default_price_list_template(document))

    def test_price_list_uses_default_cover_when_no_cover_is_uploaded(self):
        document = Document(
            document_type=Document.DocumentType.PRICE_LIST,
            title="Preisliste",
        )

        cover_path = DocumentPdfService().get_cover_pdf_path(document)

        self.assertIsNotNone(cover_path)
        self.assertEqual(cover_path.name, "cover_pricelist.pdf")

    def test_price_list_cover_date_uses_the_month_from_the_document_title(self):
        document = Document(
            document_type=Document.DocumentType.PRICE_LIST,
            title="Preisliste Mai 2026",
        )

        self.assertEqual(DocumentPdfService().get_price_list_effective_date_text(document), "ab 05/2026")

    def test_price_list_page_numbers_cover_the_complete_merged_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "preisliste.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.add_blank_page(width=595, height=842)
            with pdf_path.open("wb") as output_file:
                writer.write(output_file)

            DocumentPdfService().add_price_list_page_numbers(pdf_path)

            reader = PdfReader(str(pdf_path))
            self.assertEqual(len(reader.pages), 2)
            self.assertIn("1/2", reader.pages[0].extract_text())
            self.assertIn("2/2", reader.pages[1].extract_text())


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
            service.request_post = MagicMock()
            service.delete_conflicting_media_by_filename = MagicMock(return_value=0)
            service._upload_pdf_file = MagicMock()

            media_id = DocumentShopwareUploadService.upload_pdf(service, document)

            self.assertEqual(media_id, "existing-media-id")
            service.request_post.assert_called_once_with(
                "/_action/sync",
                payload={
                    "document-media-upsert": {
                        "entity": "media",
                        "action": "upsert",
                        "payload": [
                            {
                                "id": "existing-media-id",
                                "mediaFolderId": "d6460afa064f4c8196ed5bd0f6ccbcb5",
                            }
                        ],
                    }
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
            service.request_post = MagicMock()
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
