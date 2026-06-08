import tempfile

from django.contrib.admin.sites import AdminSite
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from documents.admin import DocumentAdmin
from documents.models import Document
from documents.services import DocumentPdfService


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
        html = admin_instance.template_syntax()
        variables_html = admin_instance.template_variables()

        self.assertIn("Django Template Engine", html)
        self.assertIn("{{ css }}", html)
        self.assertIn("Dokumente/", html)
        self.assertIn("while", html)
        self.assertIn("then", html)
        self.assertIn("category_sections", html)
        self.assertIn("row.price_display", html)
        self.assertIn("js-document-token", html)
        self.assertIn("{{ document.title }}", html)
        self.assertIn("documents_document", variables_html)
        self.assertIn("document_type", variables_html)

        media = str(admin_instance.media)
        self.assertIn("documents/admin/document_editor.css", media)
        self.assertIn("documents/admin/document_editor.js", media)


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
