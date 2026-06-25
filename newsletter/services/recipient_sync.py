from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from loguru import logger

from core.services import BaseService
from newsletter.models import NewsletterRecipient
from shopware.services import Shopware6Service


def _normalize_entity(data: Any) -> Any:
    if isinstance(data, list):
        return [_normalize_entity(item) for item in data]
    if not isinstance(data, dict):
        return data

    attributes = data.get("attributes")
    result: dict[str, Any] = {}

    if isinstance(attributes, dict):
        result.update(attributes)
        if "id" not in result and data.get("id"):
            result["id"] = data.get("id")
    else:
        result.update(data)

    for source in (data, attributes if isinstance(attributes, dict) else {}):
        for key, value in source.items():
            if key == "attributes":
                continue
            if isinstance(value, (dict, list)):
                result[key] = _normalize_entity(value)
            elif key not in result:
                result[key] = value

    return result


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_datetime(value: Any):
    if not value:
        return None
    if hasattr(value, "tzinfo"):
        return value
    return parse_datetime(_to_str(value))


class NewsletterRecipientShopwareService(Shopware6Service):
    search_path = "/search/newsletter-recipient"

    def list_recipients(
        self,
        *,
        page: int = 1,
        limit: int = 100,
        status: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "limit": limit,
            "total-count-mode": 1,
        }
        filters: list[dict[str, Any]] = []
        if status:
            filters.append(
                {
                    "type": "equals",
                    "field": "status",
                    "value": status,
                }
            )
        if email:
            filters.append(
                {
                    "type": "contains",
                    "field": "email",
                    "value": email,
                }
            )
        if filters:
            payload["filter"] = filters
        return self.request_post(self.search_path, payload=payload)


class NewsletterRecipientSyncService(BaseService):
    model = NewsletterRecipient

    def sync_from_shopware(
        self,
        *,
        limit: int | None = None,
        page_size: int = 100,
        status: str = "",
        email: str = "",
        mark_missing: bool = False,
        shopware_service: NewsletterRecipientShopwareService | None = None,
    ) -> dict[str, int]:
        page_size = max(1, min(int(page_size or 100), 500))
        service = shopware_service or NewsletterRecipientShopwareService()
        summary = {
            "seen": 0,
            "created": 0,
            "updated": 0,
            "failed": 0,
            "marked_missing": 0,
        }
        seen_shopware_ids: set[str] = set()
        page = 1

        while True:
            remaining = None if limit is None else max(limit - summary["seen"], 0)
            if remaining == 0:
                break

            batch_limit = min(page_size, remaining) if remaining is not None else page_size
            response = service.list_recipients(
                page=page,
                limit=batch_limit,
                status=status,
                email=email,
            )
            rows = (response or {}).get("data") or []
            if not rows:
                break

            for row in rows:
                summary["seen"] += 1
                try:
                    recipient, created = self.upsert_from_shopware(row)
                    seen_shopware_ids.add(recipient.shopware_id)
                except Exception as exc:
                    summary["failed"] += 1
                    logger.error("Newsletter recipient sync failed: {}", exc)
                    continue

                if created:
                    summary["created"] += 1
                else:
                    summary["updated"] += 1

            total = int((response or {}).get("total") or 0)
            if len(rows) < batch_limit:
                break
            if total and summary["seen"] >= total:
                break

            page += 1

        if mark_missing and not limit and not status and not email:
            summary["marked_missing"] = self._mark_missing(seen_shopware_ids)

        return summary

    @transaction.atomic
    def upsert_from_shopware(self, payload: dict[str, Any]) -> tuple[NewsletterRecipient, bool]:
        data = _normalize_entity(payload)
        shopware_id = _to_str(data.get("id"))
        email = _to_str(data.get("email"))
        if not shopware_id:
            raise ValueError("Shopware newsletter recipient has no id.")
        if not email:
            raise ValueError(f"Shopware newsletter recipient {shopware_id} has no email.")

        now = timezone.now()
        defaults = {
            "email": email,
            "title": _to_str(data.get("title")),
            "first_name": _to_str(data.get("firstName")),
            "last_name": _to_str(data.get("lastName")),
            "zip_code": _to_str(data.get("zipCode")),
            "city": _to_str(data.get("city")),
            "street": _to_str(data.get("street")),
            "status": _to_str(data.get("status")),
            "hash": _to_str(data.get("hash")),
            "sales_channel_id": _to_str(data.get("salesChannelId")),
            "language_id": _to_str(data.get("languageId")),
            "confirmed_at": _to_datetime(data.get("confirmedAt")),
            "remote_created_at": _to_datetime(data.get("createdAt")),
            "remote_updated_at": _to_datetime(data.get("updatedAt")),
            "last_synced_at": now,
            "is_present_in_shopware": True,
            "custom_fields": data.get("customFields") if isinstance(data.get("customFields"), dict) else {},
            "raw_data": data,
        }
        return NewsletterRecipient.objects.update_or_create(
            shopware_id=shopware_id,
            defaults=defaults,
        )

    @staticmethod
    def _mark_missing(seen_shopware_ids: set[str]) -> int:
        queryset = NewsletterRecipient.objects.filter(is_present_in_shopware=True)
        if seen_shopware_ids:
            queryset = queryset.exclude(shopware_id__in=seen_shopware_ids)
        return queryset.update(is_present_in_shopware=False, last_synced_at=timezone.now())
