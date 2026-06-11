from __future__ import annotations

import hashlib
import urllib.error
import urllib.request

from documents.models import Document
from documents.services import DocumentPdfService
from shopware.services.shopware6 import Shopware6Service


class DocumentShopwareUploadService(Shopware6Service):
    """Uploads a generated Document PDF to Shopware 6 as a Media entity."""

    @staticmethod
    def build_media_id(document: Document) -> str:
        return hashlib.md5(f"document-media:{document.slug}".encode("utf-8")).hexdigest()

    def upload_pdf(self, document: Document) -> str:
        pdf_path = DocumentPdfService().get_pdf_path(document)
        if not pdf_path or not pdf_path.exists():
            raise FileNotFoundError(
                f"PDF fuer '{document}' nicht gefunden. Zuerst 'PDF speichern' ausfuehren."
            )

        media_id = self.build_media_id(document)

        if not self.access_token:
            self.access_token = self.authenticate()

        # Create or ensure the media entity exists (idempotent)
        self.request("POST", "/api/media", payload={"id": media_id})

        # Upload binary PDF — overwrites existing file on same media_id
        file_name = pdf_path.stem
        url = self._build_url(
            f"/api/_action/media/{media_id}/upload",
            {"fileName": file_name, "extension": "pdf"},
        )
        req = urllib.request.Request(
            url=url,
            data=pdf_path.read_bytes(),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/pdf",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                self._parse_response(response.read())
        except urllib.error.HTTPError as error:
            detail = self._parse_response(error.read())
            raise RuntimeError(
                f"Shopware Media-Upload fehlgeschlagen ({error.code}): {detail}"
            ) from error

        document.shopware_media_id = media_id
        document.save(update_fields=["shopware_media_id", "updated_at"])
        return media_id
