"""Versioned source files and verified Shopware publications for downloads."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader
from weasyprint import HTML as WeasyHTML

from documents.models import ManagedDownload, ManagedDownloadVersion
from documents.services import DocumentPdfService
from shopware.services.shopware6 import Shopware6Service


class ManagedDownloadService(Shopware6Service):
    """Publish one immutable source version and verify the Shopware file bytes."""

    model = ManagedDownloadVersion

    @staticmethod
    def build_media_id(download: ManagedDownload) -> str:
        return hashlib.md5(f"managed-download:{download.slug}".encode()).hexdigest()

    def publish(self, version: ManagedDownloadVersion) -> dict[str, str]:
        version = ManagedDownloadVersion.objects.select_related(
            "download", "source_document_version__document"
        ).get(pk=version.pk)
        download = version.download
        if version.published_at:
            return {"media_id": download.shopware_media_id, "url": version.shopware_url}

        content, extension, source_hash = self._render_source(version)
        output_hash = hashlib.sha256(content).hexdigest()
        if version.source_sha256 and version.source_sha256 != source_hash:
            raise ValueError("Die gespeicherte Quelldatei wurde seit der Versionierung verändert.")
        self._save_output(version, content, extension, source_hash, output_hash)

        media_id = download.shopware_media_id or self.build_media_id(download)
        existing = self._fetch_media(media_id)
        existing_extension = str(existing.get("fileExtension") or "").lower() if existing else ""
        if existing_extension and existing_extension != extension:
            raise ValueError("Das vorhandene Shopware-Medium hat ein anderes Dateiformat.")
        file_name = str(existing.get("fileName") or "") if existing else ""
        file_name = file_name or f"gc-download-{download.slug}"
        media_payload = {"id": media_id, "title": download.title}
        if download.shopware_media_folder_id:
            media_payload["mediaFolderId"] = download.shopware_media_folder_id
        self.request_post(
            "/_action/sync",
            payload={
                "managed-download-media": {
                    "entity": "media",
                    "action": "upsert",
                    "payload": [media_payload],
                }
            },
        )
        self.request_binary(
            f"/_action/media/{media_id}/upload",
            content=content,
            additional_query_params={"fileName": file_name, "extension": extension},
        )
        media = self._fetch_media(media_id)
        url = str(media.get("url") or "") if media else ""
        if not url:
            raise RuntimeError("Shopware lieferte nach dem Upload keine Download-URL.")
        self._verify_public_file(url, output_hash)

        with transaction.atomic():
            version = ManagedDownloadVersion.objects.select_for_update().get(pk=version.pk)
            download = ManagedDownload.objects.select_for_update().get(pk=download.pk)
            if version.published_at:
                raise ValueError("Diese Version wurde zwischenzeitlich bereits veröffentlicht.")
            version.shopware_url = url
            version.published_at = timezone.now()
            version.save(update_fields=("shopware_url", "published_at", "updated_at"))
            download.shopware_media_id = media_id
            download.shopware_url = url
            download.active_version = version
            download.save(update_fields=("shopware_media_id", "shopware_url", "active_version", "updated_at"))
        return {"media_id": media_id, "url": url}

    def _render_source(self, version: ManagedDownloadVersion) -> tuple[bytes, str, str]:
        if version.source_document_version_id:
            source = version.source_document_version
            document = source.document
            if document.active_version_id != source.pk:
                raise ValueError("Die ausgewählte Dokumentversion muss zuerst aktiviert werden.")
            pdf_path = DocumentPdfService().generate_pdf(document)
            content = pdf_path.read_bytes()
            source_hash = hashlib.sha256(
                json.dumps(
                    {
                        "template_source": source.template_source,
                        "css_content": source.css_content,
                        "context_snapshot": source.context_snapshot,
                        "valid_from": source.valid_from.isoformat() if source.valid_from else None,
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            self._validate_pdf(content)
            return content, "pdf", source_hash

        if not version.source_file:
            raise ValueError("Für die Downloadversion fehlt eine Quelldatei.")
        with version.source_file.open("rb") as source_file:
            source_bytes = source_file.read()
        extension = Path(version.source_file.name).suffix.lower().lstrip(".")
        if extension not in {"pdf", "doc", "docx", "rtf", "html", "htm"}:
            raise ValueError(f"Das Quellformat .{extension} wird nicht unterstützt.")
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if extension in {"html", "htm"}:
            content = WeasyHTML(string=source_bytes.decode("utf-8"), base_url=".").write_pdf()
            self._validate_pdf(content)
            return content, "pdf", source_hash
        if extension == "pdf":
            self._validate_pdf(source_bytes)
        elif not source_bytes:
            raise ValueError("Die Quelldatei ist leer.")
        return source_bytes, extension, source_hash

    @staticmethod
    def _validate_pdf(content: bytes) -> None:
        if not content.startswith(b"%PDF-") or not PdfReader(BytesIO(content)).pages:
            raise ValueError("Die Quelldatei ist keine lesbare PDF-Datei.")

    @staticmethod
    def _save_output(
        version: ManagedDownloadVersion,
        content: bytes,
        extension: str,
        source_hash: str,
        output_hash: str,
    ) -> None:
        if version.output_file:
            with version.output_file.open("rb") as existing_file:
                existing_hash = hashlib.sha256(existing_file.read()).hexdigest()
            if existing_hash != output_hash:
                raise ValueError("Die bereits vorbereitete Ausgabedatei weicht von der Quelle ab.")
        else:
            version.output_file.save(
                f"v{version.version_number}.{extension}", ContentFile(content), save=False
            )
        version.source_sha256 = source_hash
        version.output_sha256 = output_hash
        version.output_extension = extension
        version.save(
            update_fields=("output_file", "source_sha256", "output_sha256", "output_extension", "updated_at")
        )

    def _fetch_media(self, media_id: str) -> dict:
        result = self.request_post(
            "/search/media",
            payload={"filter": [{"type": "equals", "field": "id", "value": media_id}], "limit": 1},
        )
        rows = result.get("data") or [] if isinstance(result, dict) else []
        if not rows:
            return {}
        row = rows[0]
        return row.get("attributes", row) if isinstance(row, dict) else {}

    @staticmethod
    def _verify_public_file(url: str, expected_hash: str) -> None:
        parts = urllib.parse.urlsplit(url)
        safe_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, urllib.parse.quote(parts.path, safe="/%"), parts.query, parts.fragment)
        )
        digest = hashlib.sha256()
        with urllib.request.urlopen(safe_url, timeout=60) as response:
            if response.status != 200:
                raise RuntimeError(f"Shopware-Download antwortete mit HTTP {response.status}.")
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected_hash:
            raise RuntimeError("Der Shopware-Download stimmt nicht mit der versionierten Datei überein.")
