from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from documents.models import Document
from documents.services import DocumentPdfService
from shopware.services.shopware6 import Shopware6Service


class DocumentShopwareUploadService(Shopware6Service):
    """Uploads a generated Document PDF to Shopware 6 as a Media entity."""

    media_base_path = "/media"

    @staticmethod
    def build_media_id(document: Document) -> str:
        return hashlib.md5(f"document-media:{document.slug}".encode("utf-8")).hexdigest()

    def resolve_media_id(self, document: Document) -> str:
        return (document.shopware_media_id or "").strip() or self.build_media_id(document)

    def upload_pdf(self, document: Document) -> str:
        pdf_path = DocumentPdfService().get_pdf_path(document)
        if not pdf_path or not pdf_path.exists():
            raise FileNotFoundError(
                f"PDF fuer '{document}' nicht gefunden. Zuerst 'PDF speichern' ausfuehren."
            )

        media_id = self.resolve_media_id(document)

        if not self.access_token:
            self.access_token = self.authenticate()

        # Create or ensure the media entity exists (idempotent)
        self.request("POST", "/media", payload={
            "id": media_id,
            "mediaFolderId": "d6460afa064f4c8196ed5bd0f6ccbcb5",
        })

        file_name = pdf_path.stem
        self.delete_conflicting_media_by_filename(
            file_name=file_name,
            extension="pdf",
            exclude_media_id=media_id,
        )
        try:
            self._upload_pdf_file(media_id=media_id, pdf_path=pdf_path, file_name=file_name)
        except RuntimeError as exc:
            if not self._is_duplicate_media_filename_error(exc):
                raise
            self.delete_conflicting_media_by_filename(
                file_name=file_name,
                extension="pdf",
                exclude_media_id=media_id,
            )
            self._upload_pdf_file(media_id=media_id, pdf_path=pdf_path, file_name=file_name)

        document.shopware_media_id = media_id
        document.save(update_fields=["shopware_media_id", "updated_at"])
        return media_id

    def _upload_pdf_file(self, *, media_id: str, pdf_path: Path, file_name: str) -> None:
        url = self._build_url(
            f"/_action/media/{media_id}/upload",
            {"fileName": file_name, "extension": "pdf"},
        )
        req = urllib.request.Request(
            url=url,
            data=pdf_path.read_bytes(),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/octet-stream",
                "Accept": "application/json",
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

    def find_media_ids_by_filename(self, *, file_name: str, extension: str) -> list[str]:
        payload = {
            "filter": [
                {
                    "type": "equals",
                    "field": "fileName",
                    "value": file_name,
                },
                {
                    "type": "equals",
                    "field": "fileExtension",
                    "value": extension,
                },
            ],
            "limit": 50,
        }
        result = self.request_post("/search/media", payload=payload)
        return [
            media_id
            for media_id in (self._entity_id(row) for row in (result or {}).get("data", []))
            if media_id
        ]

    def delete_media_by_ids(self, media_ids: list[str]) -> int:
        deleted = 0
        for media_id in sorted({str(value).strip() for value in media_ids if str(value).strip()}):
            self.request_delete(f"{self.media_base_path}/{media_id}")
            deleted += 1
        return deleted

    def delete_conflicting_media_by_filename(
        self,
        *,
        file_name: str,
        extension: str,
        exclude_media_id: str,
    ) -> int:
        media_ids = [
            media_id
            for media_id in self.find_media_ids_by_filename(file_name=file_name, extension=extension)
            if media_id != exclude_media_id
        ]
        return self.delete_media_by_ids(media_ids)

    @staticmethod
    def _entity_id(row: dict[str, Any]) -> str:
        if not isinstance(row, dict):
            return ""
        row_id = row.get("id")
        if row_id:
            return str(row_id).strip()
        attributes = row.get("attributes") or {}
        if isinstance(attributes, dict) and attributes.get("id"):
            return str(attributes["id"]).strip()
        return ""

    @staticmethod
    def _is_duplicate_media_filename_error(exc: Exception) -> bool:
        return "CONTENT__MEDIA_DUPLICATED_FILE_NAME" in str(exc)
