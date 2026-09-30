from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from loguru import logger

from core.services import BaseService
from customer.models import Customer
from newsletter.models import NewsletterRecipient
from shopware.services import CustomerService, Shopware6Service


_CUSTOM_FIELD_KEY_RE = re.compile(r"[^a-z0-9]+")
_ERP_CUSTOM_FIELD_ALIASES = (
    "adrnr",
    "erpnr",
    "customernumber",
)


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


def _to_erp_nr(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _to_str(value)


def _normalize_custom_field_key(value: Any) -> str:
    return _CUSTOM_FIELD_KEY_RE.sub("", _to_str(value).casefold())


def _extract_recipient_erp_nr(data: dict[str, Any]) -> str:
    custom_fields = data.get("customFields")
    if not isinstance(custom_fields, dict):
        return ""

    configured_key = _to_str(
        getattr(settings, "NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD", "AdrNr")
    )
    if configured_key and configured_key in custom_fields:
        erp_nr = _to_erp_nr(custom_fields.get(configured_key))
        if erp_nr:
            return erp_nr

    normalized_configured_key = _normalize_custom_field_key(configured_key)
    normalized_fields = [
        (_normalize_custom_field_key(key), value)
        for key, value in custom_fields.items()
    ]
    for key, value in normalized_fields:
        if normalized_configured_key and key == normalized_configured_key:
            erp_nr = _to_erp_nr(value)
            if erp_nr:
                return erp_nr

    for alias in _ERP_CUSTOM_FIELD_ALIASES:
        for key, value in normalized_fields:
            if key == alias or key.endswith(alias):
                erp_nr = _to_erp_nr(value)
                if erp_nr:
                    return erp_nr
    return ""


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
            "associations": {
                "salutation": {},
            },
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

    def relink_existing(self, *, limit: int | None = None) -> dict[str, int]:
        queryset = NewsletterRecipient.objects.order_by("pk")
        if limit is not None:
            queryset = queryset[: max(int(limit), 0)]

        summary = {"seen": 0, "updated": 0, "linked": 0, "unlinked": 0}
        for recipient in queryset.iterator():
            summary["seen"] += 1
            erp_nr = recipient.erp_nr or _extract_recipient_erp_nr(
                {"customFields": recipient.custom_fields}
            )
            customer = self._find_customer(
                erp_nr=erp_nr,
                customer_shopware_id=recipient.customer_shopware_id,
            )
            is_customer = customer is not None
            changed_fields = []
            if recipient.erp_nr != erp_nr:
                recipient.erp_nr = erp_nr
                changed_fields.append("erp_nr")
            if recipient.customer_id != getattr(customer, "pk", None):
                recipient.customer = customer
                changed_fields.append("customer")
            if recipient.is_customer != is_customer:
                recipient.is_customer = is_customer
                changed_fields.append("is_customer")
            if changed_fields:
                recipient.save(update_fields=(*changed_fields, "updated_at"))
                summary["updated"] += 1
            if is_customer:
                summary["linked"] += 1
            else:
                summary["unlinked"] += 1
        return summary

    def sync_from_shopware(
        self,
        *,
        limit: int | None = None,
        page_size: int = 100,
        status: str = "",
        email: str = "",
        mark_missing: bool = False,
        shopware_service: NewsletterRecipientShopwareService | None = None,
        customer_service: CustomerService | None = None,
    ) -> dict[str, int]:
        page_size = max(1, min(int(page_size or 100), 500))
        service = shopware_service or NewsletterRecipientShopwareService()
        customer_service = customer_service or CustomerService()
        summary = {
            "seen": 0,
            "created": 0,
            "updated": 0,
            "linked": 0,
            "unlinked": 0,
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
                    recipient, created = self.upsert_from_shopware(row, customer_service=customer_service)
                    seen_shopware_ids.add(recipient.shopware_id)
                except Exception as exc:
                    summary["failed"] += 1
                    logger.error("Newsletter recipient sync failed: {}", exc)
                    continue

                if created:
                    summary["created"] += 1
                else:
                    summary["updated"] += 1
                if recipient.customer_id:
                    summary["linked"] += 1
                else:
                    summary["unlinked"] += 1

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
    def upsert_from_shopware(
        self,
        payload: dict[str, Any],
        *,
        customer_service: CustomerService | None = None,
    ) -> tuple[NewsletterRecipient, bool]:
        data = _normalize_entity(payload)
        shopware_id = _to_str(data.get("id"))
        email = _to_str(data.get("email"))
        if not shopware_id:
            raise ValueError("Shopware newsletter recipient has no id.")
        if not email:
            raise ValueError(f"Shopware newsletter recipient {shopware_id} has no email.")

        now = timezone.now()
        salutation = data.get("salutation") if isinstance(data.get("salutation"), dict) else {}
        erp_nr, customer_shopware_id, customer = self._resolve_customer_reference(
            data=data,
            customer_service=customer_service,
        )
        defaults = {
            "customer_shopware_id": customer_shopware_id,
            "erp_nr": erp_nr,
            "customer": customer,
            "is_customer": customer is not None,
            "email": email,
            "title": _to_str(data.get("title")),
            "salutation_id": _to_str(data.get("salutationId")) or _to_str(salutation.get("id")),
            "salutation_key": _to_str(salutation.get("salutationKey")),
            "salutation_display_name": _to_str(salutation.get("displayName")),
            "salutation_letter_name": _to_str(salutation.get("letterName")),
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
    def _extract_customer_shopware_id(data: dict[str, Any]) -> str:
        customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
        return _to_str(data.get("customerId")) or _to_str(customer.get("id"))

    def _resolve_customer_reference(
        self,
        *,
        data: dict[str, Any],
        customer_service: CustomerService | None,
    ) -> tuple[str, str, Customer | None]:
        erp_nr = _extract_recipient_erp_nr(data)
        customer_shopware_id = self._extract_customer_shopware_id(data)
        customer = self._find_customer(
            erp_nr=erp_nr,
            customer_shopware_id=customer_shopware_id,
        )
        if customer is not None:
            return erp_nr or customer.erp_nr, customer_shopware_id or customer.api_id, customer

        email = _to_str(data.get("email")).lower()
        sales_channel_id = _to_str(data.get("salesChannelId"))
        if not email or customer_service is None:
            return erp_nr, customer_shopware_id, None

        cache = getattr(self, "_shopware_customer_id_cache", None)
        if cache is None:
            cache = {}
            self._shopware_customer_id_cache = cache

        cache_key = (email, sales_channel_id)
        if cache_key in cache:
            lookup_shopware_id, lookup_erp_nr = cache[cache_key]
        else:
            lookup_shopware_id = ""
            lookup_erp_nr = ""
            try:
                response = customer_service.get_by_email(
                    email=email,
                    sales_channel_id=sales_channel_id,
                    limit=2,
                )
                rows = (response or {}).get("data", []) or []
                total = int((response or {}).get("total") or len(rows))
                if len(rows) == 1 and total == 1:
                    customer_data = _normalize_entity(rows[0])
                    lookup_shopware_id = _to_str(customer_data.get("id"))
                    lookup_erp_nr = _to_erp_nr(customer_data.get("customerNumber"))
                elif total > 1 or len(rows) > 1:
                    logger.warning(
                        "Shopware customer lookup by email is ambiguous for {} in sales channel {}.",
                        email,
                        sales_channel_id or "-",
                    )
            except Exception as exc:  # pragma: no cover - remote runtime behavior
                logger.warning("Shopware customer lookup by email failed for {}: {}", email, exc)

            cache[cache_key] = (lookup_shopware_id, lookup_erp_nr)

        erp_nr = erp_nr or lookup_erp_nr
        customer_shopware_id = customer_shopware_id or lookup_shopware_id
        customer = self._find_customer(
            erp_nr=erp_nr,
            customer_shopware_id=customer_shopware_id,
        )
        return erp_nr, customer_shopware_id, customer

    @staticmethod
    def _find_customer(*, erp_nr: str, customer_shopware_id: str) -> Customer | None:
        erp_nr = _to_erp_nr(erp_nr)
        customer_shopware_id = _to_str(customer_shopware_id)
        erp_customer = (
            Customer.objects.filter(erp_nr__iexact=erp_nr).first()
            if erp_nr
            else None
        )
        shopware_customer = (
            Customer.objects.filter(api_id__iexact=customer_shopware_id).order_by("pk").first()
            if customer_shopware_id
            else None
        )
        if (
            erp_customer is not None
            and shopware_customer is not None
            and erp_customer.pk != shopware_customer.pk
        ):
            logger.warning(
                "Newsletter recipient customer conflict: AdrNr {} resolves to customer {}, "
                "Shopware customer id {} resolves to customer {}. AdrNr match wins.",
                erp_nr,
                erp_customer.pk,
                customer_shopware_id,
                shopware_customer.pk,
            )
        if (
            erp_nr
            and erp_customer is None
            and shopware_customer is not None
            and _to_erp_nr(shopware_customer.erp_nr).casefold() != erp_nr.casefold()
        ):
            logger.warning(
                "Newsletter recipient customer conflict: AdrNr {} has no local match, "
                "but Shopware customer id {} belongs to local ERP number {}. Recipient stays unlinked.",
                erp_nr,
                customer_shopware_id,
                shopware_customer.erp_nr,
            )
            return None
        return erp_customer or shopware_customer

    @staticmethod
    def _mark_missing(seen_shopware_ids: set[str]) -> int:
        queryset = NewsletterRecipient.objects.filter(is_present_in_shopware=True)
        if seen_shopware_ids:
            queryset = queryset.exclude(shopware_id__in=seen_shopware_ids)
        return queryset.update(is_present_in_shopware=False, last_synced_at=timezone.now())
