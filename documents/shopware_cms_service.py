from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from django.utils import timezone

from documents.models import ShopwareCmsPage, ShopwareCmsSlot
from shopware.services.shopware6 import Shopware6Service


class ShopwareCmsPageService(Shopware6Service):
    """Mirror editable Shopware CMS content locally without replacing page layouts."""

    model = ShopwareCmsPage
    PAGE_SEARCH_PATH = "/search/cms-page"
    PAGE_ASSOCIATIONS = {
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

    def fetch_pages(self) -> dict[str, int]:
        pages = self._fetch_all_pages()
        imported_slots = 0
        for payload in pages:
            _, slot_count = self.import_page(payload)
            imported_slots += slot_count
        return {"pages": len(pages), "html_slots": imported_slots}

    def fetch_page(self, *, shopware_id: str) -> ShopwareCmsPage:
        result = self.request_post(
            self.PAGE_SEARCH_PATH,
            payload={
                "filter": [{"type": "equals", "field": "id", "value": shopware_id}],
                "associations": self.PAGE_ASSOCIATIONS,
                "limit": 1,
            },
        )
        rows = self._rows(result)
        if not rows:
            raise ValueError(f"Shopware CMS-Seite {shopware_id} wurde nicht gefunden.")
        page, _ = self.import_page(rows[0])
        return page

    def import_page(self, payload: dict[str, Any]) -> tuple[ShopwareCmsPage, int]:
        shopware_id = self._value(payload, "id")
        if not shopware_id:
            raise ValueError("Shopware CMS-Seite ohne ID kann nicht importiert werden.")

        slots = list(self._iter_slots(payload))
        page, _ = ShopwareCmsPage.objects.update_or_create(
            shopware_id=shopware_id,
            defaults={
                "title": self._value(payload, "name") or shopware_id,
                "page_type": self._value(payload, "type"),
                "is_locked": self._bool_value(payload, "locked"),
                "layout_description": self._layout_description(slots),
                "remote_payload": payload,
                "last_fetched_at": timezone.now(),
            },
        )

        editable_slot_count = 0
        for slot in slots:
            html_content = self._editable_html(slot["config"])
            if html_content is None:
                continue
            editable_slot_count += 1
            local_slot = ShopwareCmsSlot.objects.filter(shopware_id=slot["shopware_id"]).first()
            if local_slot is None:
                ShopwareCmsSlot.objects.create(
                    page=page,
                    shopware_id=slot["shopware_id"],
                    slot_type=slot["slot_type"],
                    slot_label=slot["slot_label"],
                    html_content=html_content,
                    remote_html_content=html_content,
                    slot_config=slot["config"],
                )
                continue

            keep_local_html = local_slot.has_local_changes
            local_slot.page = page
            local_slot.slot_type = slot["slot_type"]
            local_slot.slot_label = slot["slot_label"]
            local_slot.remote_html_content = html_content
            local_slot.slot_config = slot["config"]
            if not keep_local_html:
                local_slot.html_content = html_content
            local_slot.save()

        return page, editable_slot_count

    def sync_page(self, page: ShopwareCmsPage) -> dict[str, Any]:
        synced = 0
        skipped = 0
        errors: list[str] = []
        for slot in page.html_slots.order_by("slot_label", "shopware_id"):
            if not slot.has_local_changes:
                skipped += 1
                continue
            try:
                self.sync_slot(slot)
            except Exception as exc:
                errors.append(f"{slot.slot_label}: {exc}")
            else:
                synced += 1

        if synced:
            page.last_synced_at = timezone.now()
            page.save(update_fields=("last_synced_at", "updated_at"))
        return {"synced": synced, "skipped": skipped, "errors": errors}

    def sync_pages(self, pages) -> dict[str, Any]:
        synced = 0
        skipped = 0
        errors: list[str] = []
        for page in pages:
            result = self.sync_page(page)
            synced += result["synced"]
            skipped += result["skipped"]
            errors.extend(f"{page}: {error}" for error in result["errors"])
        return {"synced": synced, "skipped": skipped, "errors": errors}

    def sync_slot(self, slot: ShopwareCmsSlot) -> None:
        config = deepcopy(slot.slot_config or {})
        content = config.get("content")
        if not isinstance(content, dict):
            raise ValueError("Der Shopware-Slot hat keinen statischen HTML-Inhalt.")
        if str(content.get("source") or "static") != "static":
            raise ValueError("Nur statische Shopware-Inhalte koennen lokal bearbeitet werden.")

        config["content"] = {**content, "source": "static", "value": slot.html_content}
        self.request_post(
            "/_action/sync",
            payload={
                "shop-page-slot-upsert": {
                    "entity": "cms_slot",
                    "action": "upsert",
                    "payload": [{"id": slot.shopware_id, "config": config}],
                }
            },
        )
        slot.slot_config = config
        slot.remote_html_content = slot.html_content
        slot.last_synced_at = timezone.now()
        slot.save(update_fields=(
            "slot_config",
            "remote_html_content",
            "last_synced_at",
            "updated_at",
        ))

    def _fetch_all_pages(self) -> list[dict[str, Any]]:
        page_number = 1
        page_size = 100
        pages: list[dict[str, Any]] = []
        while True:
            result = self.request_post(
                self.PAGE_SEARCH_PATH,
                payload={
                    "page": page_number,
                    "limit": page_size,
                    "associations": self.PAGE_ASSOCIATIONS,
                },
            )
            rows = self._rows(result)
            pages.extend(rows)
            total = int((result or {}).get("total") or 0) if isinstance(result, dict) else 0
            if not rows or len(rows) < page_size or (total and len(pages) >= total):
                return pages
            page_number += 1

    @classmethod
    def _iter_slots(cls, page: dict[str, Any]):
        for section_index, section in enumerate(cls._association(page, "sections"), start=1):
            section_position = cls._value(section, "position") or str(section_index)
            for block_index, block in enumerate(cls._association(section, "blocks"), start=1):
                block_position = cls._value(block, "position") or str(block_index)
                for slot_index, slot in enumerate(cls._association(block, "slots"), start=1):
                    shopware_id = cls._value(slot, "id")
                    if not shopware_id:
                        continue
                    slot_position = cls._value(slot, "slot") or cls._value(slot, "position") or str(slot_index)
                    yield {
                        "shopware_id": shopware_id,
                        "slot_type": cls._value(slot, "type") or "unbekannt",
                        "slot_label": (
                            f"Abschnitt {section_position} · Block {block_position} · Slot {slot_position}"
                        ),
                        "config": deepcopy(cls._value(slot, "config") or {}),
                    }

    @classmethod
    def _layout_description(cls, slots: list[dict[str, Any]]) -> str:
        counts = Counter(slot["slot_type"] for slot in slots)
        slot_summary = ", ".join(
            f"{slot_type}: {count}" for slot_type, count in sorted(counts.items())
        ) or "keine Slots"
        editable = sum(1 for slot in slots if cls._editable_html(slot["config"]) is not None)
        return f"{len(slots)} Inhaltselemente ({slot_summary}). {editable} HTML-Inhalte lokal bearbeitbar."

    @staticmethod
    def _rows(result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return []
        rows = result.get("data") or []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _association(row: dict[str, Any], name: str) -> list[dict[str, Any]]:
        value = ShopwareCmsPageService._value(row, name)
        if isinstance(value, dict):
            value = value.get("data") or []
        if value is None:
            relationships = row.get("relationships") or {}
            relation = relationships.get(name) if isinstance(relationships, dict) else None
            value = relation.get("data") if isinstance(relation, dict) else []
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _value(row: dict[str, Any], name: str) -> Any:
        if name in row:
            return row[name]
        attributes = row.get("attributes") or {}
        return attributes.get(name) if isinstance(attributes, dict) else None

    @classmethod
    def _bool_value(cls, row: dict[str, Any], name: str) -> bool:
        return bool(cls._value(row, name))

    @staticmethod
    def _editable_html(config: dict[str, Any]) -> str | None:
        content = config.get("content") if isinstance(config, dict) else None
        if not isinstance(content, dict):
            return None
        if str(content.get("source") or "static") != "static":
            return None
        value = content.get("value")
        return value if isinstance(value, str) else None
