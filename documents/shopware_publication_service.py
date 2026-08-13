from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from documents.models import Document
from documents.services import DocumentPdfService
from documents.shopware_upload_service import DocumentShopwareUploadService
from shopware.services.shopware6 import Shopware6Service


class DocumentShopwarePublicationService(Shopware6Service):
    """Publish one document to its selected Shopware CMS page and PDF media."""

    CMS_PAGE_SEARCH_PATH = "/search/cms-page"
    CMS_PAGE_ASSOCIATIONS = {
        "sections": {
            "associations": {
                "blocks": {
                    "associations": {
                        "slots": {},
                    }
                }
            }
        }
    }
    PUBLISHABLE_PAGE_TYPES = {"page", "landingpage"}

    def list_layout_choices(self) -> list[tuple[str, str]]:
        """Return Shopware shop and landing pages for the document admin select."""

        choices: list[tuple[str, str]] = []
        for page in self._search_all(
            self.CMS_PAGE_SEARCH_PATH,
            payload={"sort": [{"field": "name", "order": "ASC"}]},
        ):
            page_id = self._value(page, "id")
            page_type = str(self._value(page, "type") or "")
            if not page_id or page_type not in self.PUBLISHABLE_PAGE_TYPES:
                continue
            title = str(self._value(page, "name") or page_id)
            choices.append((str(page_id), f"{title} ({page_type})"))
        return choices

    def list_pdf_media_choices(self) -> list[tuple[str, str]]:
        """Return existing Shopware PDF media for the document admin select."""

        choices: list[tuple[str, str]] = []
        for media in self._search_all(
            "/search/media",
            payload={
                "filter": [
                    {
                        "type": "equals",
                        "field": "fileExtension",
                        "value": "pdf",
                    }
                ],
                "sort": [{"field": "fileName", "order": "ASC"}],
            },
        ):
            media_id = self._value(media, "id")
            if not media_id:
                continue
            file_name = str(self._value(media, "fileName") or media_id)
            extension = str(self._value(media, "fileExtension") or "pdf")
            choices.append((str(media_id), f"{file_name}.{extension}"))
        return choices

    def publish(self, document: Document) -> dict[str, str]:
        """Publish the current document HTML and a newly generated PDF to Shopware."""

        self.validate_links(document)
        self._fetch_pdf_media(document.shopware_media_id)

        # The local file is intentionally recreated for every publication.  This
        # makes a separate content hash unnecessary and guarantees that the PDF
        # uploaded below represents the currently saved document HTML.
        pdf_service = DocumentPdfService()
        rendered_html = pdf_service.render_document_html(document)
        pdf_service.generate_pdf(document)
        slot_id = self.publish_layout(document, rendered_html=rendered_html)
        media_id = DocumentShopwareUploadService().upload_pdf(document)
        return {
            "cms_page_id": document.shopware_cms_page_id,
            "cms_slot_id": slot_id,
            "media_id": media_id,
        }

    def publish_layout(self, document: Document, *, rendered_html: str) -> str:
        page = self._fetch_cms_page(document.shopware_cms_page_id)
        html_slots = [
            slot
            for slot in self._iter_slots(page)
            if self._static_html_content(slot["config"]) is not None
        ]

        # A page that already offers exactly one text element is updated in place,
        # which leaves everything else on that page untouched.
        if len(html_slots) == 1:
            slot = html_slots[0]
            config = deepcopy(slot["config"])
            content = config["content"]
            config["content"] = {**content, "source": "static", "value": rendered_html}
            self.request_post(
                "/_action/sync",
                payload={
                    "document-cms-slot-upsert": {
                        "entity": "cms_slot",
                        "action": "upsert",
                        "payload": [{"id": slot["id"], "config": config}],
                    }
                },
            )
            return slot["id"]

        # No text element at all, or several of them: Shopware has no "page HTML"
        # to overwrite, so the layout is rebuilt as a single text element that
        # holds the rendered document. Everything else on the page is discarded.
        return self._rebuild_layout(page, rendered_html=rendered_html)

    def _rebuild_layout(self, page: dict[str, Any], *, rendered_html: str) -> str:
        page_id = str(self._value(page, "id"))
        obsolete_section_ids = [
            str(self._value(section, "id"))
            for section in self._association(page, "sections")
            if self._value(section, "id")
        ]

        section_id = uuid4().hex
        block_id = uuid4().hex
        slot_id = uuid4().hex
        operations: dict[str, Any] = {
            "document-cms-page-upsert": {
                "entity": "cms_page",
                "action": "upsert",
                "payload": [
                    {
                        "id": page_id,
                        "sections": [
                            {
                                "id": section_id,
                                "type": "default",
                                "position": 0,
                                "sizingMode": "boxed",
                                "mobileBehavior": "wrap",
                                "blocks": [
                                    {
                                        "id": block_id,
                                        "type": "text",
                                        "position": 0,
                                        "sectionPosition": "main",
                                        "marginTop": "20px",
                                        "marginBottom": "20px",
                                        "marginLeft": "20px",
                                        "marginRight": "20px",
                                        "slots": [
                                            {
                                                "id": slot_id,
                                                "type": "text",
                                                "slot": "content",
                                                # Only "content" is set: the client strips None
                                                # values, and Shopware rejects a field config
                                                # that carries a source without a value.
                                                "config": {
                                                    "content": {
                                                        "source": "static",
                                                        "value": rendered_html,
                                                    },
                                                },
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        # Upserting sections does not remove the previous ones, so they are
        # deleted explicitly - after the new section exists, never before.
        if obsolete_section_ids:
            operations["document-cms-section-delete"] = {
                "entity": "cms_section",
                "action": "delete",
                "payload": [{"id": obsolete_id} for obsolete_id in obsolete_section_ids],
            }

        self.request_post("/_action/sync", payload=operations)
        return slot_id

    def _fetch_cms_page(self, cms_page_id: str) -> dict[str, Any]:
        result = self.request_post(
            self.CMS_PAGE_SEARCH_PATH,
            payload={
                "filter": [{"type": "equals", "field": "id", "value": cms_page_id}],
                "associations": self.CMS_PAGE_ASSOCIATIONS,
                "limit": 1,
            },
        )
        rows = self._rows(result)
        if not rows:
            raise ValueError(f"Shopware-Erlebniswelt {cms_page_id} wurde nicht gefunden.")
        return rows[0]

    def _fetch_pdf_media(self, media_id: str) -> dict[str, Any]:
        result = self.request_post(
            "/search/media",
            payload={
                "filter": [{"type": "equals", "field": "id", "value": media_id}],
                "limit": 1,
            },
        )
        rows = self._rows(result)
        if not rows:
            raise ValueError(
                f"Die ausgewählte Shopware-PDF-Datei {media_id} wurde nicht gefunden. "
                "Bitte eine vorhandene PDF-Datei auswählen und speichern."
            )
        extension = str(self._value(rows[0], "fileExtension") or "").lower()
        if extension != "pdf":
            raise ValueError(
                f"Die ausgewählte Shopware-Mediendatei {media_id} ist keine PDF-Datei. "
                "Bitte eine PDF-Datei auswählen und speichern."
            )
        return rows[0]

    def _search_all(self, path: str, *, payload: dict[str, Any]) -> list[dict[str, Any]]:
        page_number = 1
        page_size = 100
        rows: list[dict[str, Any]] = []
        while True:
            result = self.request_post(path, payload={**payload, "page": page_number, "limit": page_size})
            current_rows = self._rows(result)
            rows.extend(current_rows)
            total = int((result or {}).get("total") or 0) if isinstance(result, dict) else 0
            if not current_rows or len(current_rows) < page_size or (total and len(rows) >= total):
                return rows
            page_number += 1

    @staticmethod
    def validate_links(document: Document) -> None:
        if not document.shopware_cms_page_id:
            raise ValueError("Bitte zuerst eine Shopware-Erlebniswelt auswählen und speichern.")
        if not document.shopware_media_id:
            raise ValueError("Bitte zuerst eine Shopware-PDF-Datei auswählen und speichern.")

    @classmethod
    def _iter_slots(cls, page: dict[str, Any]):
        for section in cls._association(page, "sections"):
            for block in cls._association(section, "blocks"):
                for slot in cls._association(block, "slots"):
                    slot_id = cls._value(slot, "id")
                    if slot_id:
                        yield {
                            "id": str(slot_id),
                            "config": deepcopy(cls._value(slot, "config") or {}),
                        }

    @staticmethod
    def _static_html_content(config: dict[str, Any]) -> str | None:
        content = config.get("content") if isinstance(config, dict) else None
        if not isinstance(content, dict) or str(content.get("source") or "static") != "static":
            return None
        value = content.get("value")
        return value if isinstance(value, str) else None

    @staticmethod
    def _rows(result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return []
        rows = result.get("data") or []
        return [row for row in rows if isinstance(row, dict)]

    @classmethod
    def _association(cls, row: dict[str, Any], name: str) -> list[dict[str, Any]]:
        value = cls._value(row, name)
        if isinstance(value, dict):
            value = value.get("data") or []
        if value is None:
            relationships = row.get("relationships") or {}
            relationship = relationships.get(name) if isinstance(relationships, dict) else None
            value = relationship.get("data") if isinstance(relationship, dict) else []
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _value(row: dict[str, Any], name: str) -> Any:
        if name in row:
            return row[name]
        attributes = row.get("attributes") or {}
        return attributes.get(name) if isinstance(attributes, dict) else None
