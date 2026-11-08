"""Checks for versioned download conversion before Shopware publication."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from hashlib import sha256

from django.core.files.base import ContentFile
from django.test import SimpleTestCase
from pypdf import PdfReader, PdfWriter

from documents.managed_download_service import ManagedDownloadService


class ManagedDownloadServiceTests(SimpleTestCase):
    def setUp(self):
        self.service = ManagedDownloadService.__new__(ManagedDownloadService)

    @staticmethod
    def source(name: str, content: bytes):
        file = ContentFile(content, name=name)
        return SimpleNamespace(source_document_version_id=None, source_file=file)

    def test_valid_pdf_is_kept_byte_for_byte(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = BytesIO()
        writer.write(buffer)
        original = buffer.getvalue()

        output, extension, source_hash = self.service._render_source(self.source("catalog.pdf", original))

        self.assertEqual(output, original)
        self.assertEqual(extension, "pdf")
        self.assertEqual(len(PdfReader(BytesIO(output)).pages), 1)
        self.assertEqual(len(source_hash), 64)

    def test_broken_pdf_cannot_be_published(self):
        with self.assertRaises(ValueError):
            self.service._render_source(self.source("catalog.pdf", b"not a PDF"))

    def test_word_template_is_kept_in_original_format(self):
        original = b"word-template-binary"

        output, extension, _ = self.service._render_source(self.source("template.docx", original))

        self.assertEqual((output, extension), (original, "docx"))

    def test_html_source_is_converted_to_readable_pdf(self):
        source = self.source("notice.html", b"<html><body><h1>Notice</h1></body></html>")

        output, extension, _ = self.service._render_source(source)

        self.assertEqual(extension, "pdf")
        self.assertEqual(len(PdfReader(BytesIO(output)).pages), 1)

    def test_public_verification_retries_stale_shopware_bytes(self):
        stale = BytesIO(b"stale")
        stale.status = 200
        current = BytesIO(b"current")
        current.status = 200

        with patch("documents.managed_download_service.urllib.request.urlopen", side_effect=[stale, current]) as open_url:
            with patch("documents.managed_download_service.time.sleep") as sleep:
                self.service._verify_public_file("https://example.com/file.pdf", sha256(b"current").hexdigest())

        self.assertEqual(open_url.call_count, 2)
        sleep.assert_called_once_with(2)
