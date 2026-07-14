from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.text import slugify
from loguru import logger

from core.services import BaseService
from products.models import Category
from shopware.services.shopware6 import Shopware6Service


class ShopwareCategorySyncService(BaseService):
    """Importiert Shopware-6-Kategorien inklusive ihrer Übersetzungen in die Bridge."""

    model = Category
    search_path = "/search/category"

    def sync_from_shopware(
        self,
        *,
        limit: int | None = None,
        page_size: int = 100,
        shopware_service: Shopware6Service | None = None,
    ) -> dict[str, int]:
        page_size = max(1, min(int(page_size or 100), 500))
        service = shopware_service or Shopware6Service()
        rows: list[dict[str, Any]] = []
        page = 1

        while True:
            remaining = None if limit is None else max(limit - len(rows), 0)
            if remaining == 0:
                break

            batch_limit = min(page_size, remaining) if remaining is not None else page_size
            response = service.request_post(
                self.search_path,
                payload=self._search_payload(page=page, limit=batch_limit),
            )
            batch = [row for row in ((response or {}).get("data") or []) if isinstance(row, dict)]
            if not batch:
                break
            rows.extend(batch)

            total = self._to_int((response or {}).get("total"))
            if len(batch) < batch_limit or (total and len(rows) >= total):
                break
            page += 1

        return self._upsert_categories(rows)

    @classmethod
    def _search_payload(cls, *, page: int, limit: int) -> dict[str, Any]:
        return {
            "page": page,
            "limit": limit,
            "total-count-mode": 1,
            "associations": {
                "translations": {
                    "associations": {
                        "language": {
                            "associations": {
                                "locale": {},
                            },
                        },
                    },
                },
            },
        }

    def _upsert_categories(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "seen": len(rows),
            "created": 0,
            "updated": 0,
            "skipped": 0,
        }
        remote_categories: dict[str, dict[str, Any]] = {}
        for row in rows:
            category = self._normalize_entity(row)
            sw6_id = self._text(category.get("id"))
            name = self._text(category.get("name"))
            if not sw6_id or not name:
                summary["skipped"] += 1
                logger.warning("Skipping Shopware category without id or name: {}", row)
                continue
            remote_categories[sw6_id] = category

        if not remote_categories:
            return summary

        remote_ids = set(remote_categories)
        parent_ids = {
            self._text(category.get("parentId"))
            for category in remote_categories.values()
            if self._text(category.get("parentId"))
        }
        categories_by_sw6_id = {
            category.sw6_id: category
            for category in Category.objects.filter(sw6_id__in=remote_ids | parent_ids)
            if category.sw6_id
        }
        categories_by_legacy_sku = {
            category.sku: category
            for category in Category.objects.filter(sku__in=remote_ids)
            if category.sku
        }

        with transaction.atomic(), Category.objects.disable_mptt_updates():
            for sw6_id, remote_category in remote_categories.items():
                category = categories_by_sw6_id.get(sw6_id)
                if category is None:
                    category = categories_by_legacy_sku.get(sw6_id)

                defaults = self._category_defaults(remote_category)
                translations = self._translation_defaults(remote_category)
                if category is None:
                    category = Category(
                        sw6_id=sw6_id,
                        slug=self._build_unique_slug(defaults["name"], sw6_id),
                        **defaults,
                    )
                    summary["created"] += 1
                else:
                    for field_name, value in defaults.items():
                        setattr(category, field_name, value)
                    category.sw6_id = sw6_id
                    summary["updated"] += 1

                for field_name, value in translations.items():
                    setattr(category, field_name, value)
                category.save()
                categories_by_sw6_id[sw6_id] = category

            for sw6_id, remote_category in remote_categories.items():
                parent_sw6_id = self._text(remote_category.get("parentId"))
                category = categories_by_sw6_id[sw6_id]
                if not parent_sw6_id:
                    Category.objects.filter(pk=category.pk).update(parent_id=None)
                    continue

                parent = categories_by_sw6_id.get(parent_sw6_id)
                if parent is None:
                    logger.warning(
                        "Shopware category {} references unavailable parent {}.",
                        sw6_id,
                        parent_sw6_id,
                    )
                    continue
                if parent.pk != category.pk:
                    Category.objects.filter(pk=category.pk).update(parent_id=parent.pk)

            Category.objects.rebuild()

        return summary

    @classmethod
    def _category_defaults(cls, category: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": cls._truncate(category.get("name"), 128),
            "description": cls._text(category.get("description")),
            "meta_title": cls._truncate(category.get("metaTitle"), 255),
            "meta_description": cls._text(category.get("metaDescription")),
            "meta_keywords": cls._truncate(category.get("keywords"), 255),
            "is_active": cls._to_bool(category.get("active"), default=True),
            "is_visible": cls._to_bool(category.get("visible"), default=True),
        }

    @classmethod
    def _translation_defaults(cls, category: dict[str, Any]) -> dict[str, str]:
        defaults: dict[str, str] = {}
        translations = category.get("translations") or []
        if not isinstance(translations, list):
            return defaults

        fields = {
            "name": ("name", 128),
            "description": ("description", None),
            "meta_title": ("metaTitle", 255),
            "meta_description": ("metaDescription", None),
            "meta_keywords": ("keywords", 255),
        }
        for translation in translations:
            data = cls._normalize_entity(translation)
            language_suffix = cls._language_suffix(data)
            if not language_suffix:
                continue
            for model_field, (shopware_field, max_length) in fields.items():
                if shopware_field not in data:
                    continue
                value = cls._text(data.get(shopware_field))
                defaults[f"{model_field}_{language_suffix}"] = (
                    cls._truncate(value, max_length) if max_length else value
                )
        return defaults

    @classmethod
    def _language_suffix(cls, translation: dict[str, Any]) -> str:
        language = translation.get("language") if isinstance(translation.get("language"), dict) else {}
        locale = language.get("locale") if isinstance(language.get("locale"), dict) else {}
        locale_code = cls._text(
            translation.get("localeCode")
            or translation.get("locale")
            or language.get("localeCode")
            or locale.get("code")
        ).lower().replace("_", "-")
        return {
            "de": "de",
            "de-de": "de",
            "en": "en",
            "en-gb": "en",
            "en-us": "en",
            "ch-de": "ch_de",
            "de-ch": "ch_de",
            "it-de": "it_de",
            "de-it": "it_de",
            "it-it": "it_it",
        }.get(locale_code, "")

    @classmethod
    def _build_unique_slug(cls, name: str, sw6_id: str) -> str:
        base_slug = slugify(name) or "kategorie"
        suffix = sw6_id[:8]
        candidate = base_slug[: 160 - len(suffix) - 1] + f"-{suffix}"
        index = 2
        while Category.objects.filter(slug=candidate).exists():
            indexed_suffix = f"-{suffix}-{index}"
            candidate = base_slug[: 160 - len(indexed_suffix)] + indexed_suffix
            index += 1
        return candidate

    @classmethod
    def _normalize_entity(cls, payload: dict[str, Any]) -> dict[str, Any]:
        attributes = payload.get("attributes")
        normalized = dict(attributes) if isinstance(attributes, dict) else dict(payload)
        normalized.setdefault("id", payload.get("id"))
        for source in (payload, attributes if isinstance(attributes, dict) else {}):
            for field_name, value in source.items():
                if field_name == "attributes":
                    continue
                if isinstance(value, dict):
                    normalized[field_name] = cls._normalize_entity(value)
                elif isinstance(value, list):
                    normalized[field_name] = [
                        cls._normalize_entity(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                elif field_name not in normalized:
                    normalized[field_name] = value
        return normalized

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @classmethod
    def _truncate(cls, value: Any, max_length: int | None) -> str:
        text = cls._text(value)
        return text[:max_length] if max_length else text

    @staticmethod
    def _to_bool(value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
