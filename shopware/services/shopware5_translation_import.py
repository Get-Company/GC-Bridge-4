from __future__ import annotations

from typing import Any, Iterable

from loguru import logger

from core.services import BaseService
from products.models import Product

from .shopware5 import Shopware5APIError, Shopware5ProductSyncService


class Shopware5ItalianTranslationImportService(BaseService):
    """Importiert vorhandene italienische Artikeltexte aus Shopware 5 nach Django."""

    model = Product
    italian_locales = {"it_it", "it-it"}
    italian_category_root_name = "Italien"
    technical_category_root_name = "Shopware"
    page_size = 500
    field_mapping = {
        "name": "name_it_it",
        "description": "description_short_it_it",
        "descriptionLong": "description_it_it",
        "packUnit": "unit_it_it",
    }

    def __init__(self, *, api_service: Shopware5ProductSyncService | None = None) -> None:
        self.api_service = api_service or Shopware5ProductSyncService()

    def import_products(
        self,
        products: Iterable[Product],
        *,
        dry_run: bool = False,
        italian_shop_id: str | None = None,
    ) -> dict[str, object]:
        self._validate_api_config()
        italian_shop_ids = self._italian_shop_ids(italian_shop_id=italian_shop_id)
        summary: dict[str, object] = {
            "processed": 0,
            "updated": 0,
            "unchanged": 0,
            "missing_translation": 0,
            "errors": 0,
            "error_details": [],
        }

        for product in products:
            summary["processed"] = int(summary["processed"]) + 1
            try:
                result = self.import_product(
                    product,
                    italian_shop_ids=italian_shop_ids,
                    dry_run=dry_run,
                )
                summary[result] = int(summary[result]) + 1
            except Exception as exc:
                summary["errors"] = int(summary["errors"]) + 1
                detail = {"erp_nr": getattr(product, "erp_nr", ""), "error": str(exc)}
                error_details = summary["error_details"]
                if isinstance(error_details, list):
                    error_details.append(detail)
                logger.warning(
                    "Shopware5 Italian translation import failed for {}: {}",
                    getattr(product, "erp_nr", ""),
                    exc,
                )

        return summary

    def import_product(
        self,
        product: Product,
        *,
        italian_shop_ids: set[str],
        dry_run: bool = False,
    ) -> str:
        product_number = str(product.erp_nr or "").strip()
        if not product_number:
            raise ValueError("Product has no ERP number.")

        article = self.api_service.get_article_by_number(product_number)
        translation = self._italian_translation(article, italian_shop_ids)
        if translation is None:
            return "missing_translation"

        changed_fields = self._apply_translation(product, translation)
        if not changed_fields:
            return "unchanged"
        if not dry_run:
            product.save(update_fields=changed_fields)
        return "updated"

    def _validate_api_config(self) -> None:
        validate = getattr(self.api_service, "_validate_config", None)
        if callable(validate):
            validate()

    def _italian_shop_ids(self, *, italian_shop_id: str | None = None) -> set[str]:
        explicit_shop_id = self._text(italian_shop_id)
        if explicit_shop_id:
            return {explicit_shop_id}

        shops = self._get_paged_rows(path="/shops")

        italian_shop_ids = {
            shop_id
            for shop in shops
            if isinstance(shop, dict)
            if (shop_id := self._text(shop.get("id")))
            if self._is_italian_locale(shop.get("locale"))
        }
        if italian_shop_ids:
            return italian_shop_ids

        italian_category_ids = self._italian_category_ids()
        italian_shop_ids = {
            shop_id
            for shop in shops
            if isinstance(shop, dict)
            if (shop_id := self._text(shop.get("id")))
            if self._text(shop.get("categoryId")) in italian_category_ids
        }
        if italian_shop_ids:
            return italian_shop_ids

        raise Shopware5APIError(
            "No Italian Shopware5 language shop was found. "
            "Expected locale it_IT or a shop assigned to category root 'Italien'. "
            "Use --shop-id <SW5_SHOP_ID> to select the source shop explicitly."
        )

    def _italian_category_ids(self) -> set[str]:
        categories = self._get_paged_rows(path="/categories")

        categories_by_id = {
            category_id: category
            for category in categories
            if isinstance(category, dict)
            if (category_id := self._text(category.get("id")))
        }
        candidates = [
            category_id
            for category_id, category in categories_by_id.items()
            if self._normalized_name(category.get("name"))
            == self._normalized_name(self.italian_category_root_name)
        ]
        direct_children_of_technical_root = [
            category_id
            for category_id in candidates
            if self._normalized_name(
                categories_by_id.get(self._text(categories_by_id[category_id].get("parentId")), {}).get("name")
            )
            == self._normalized_name(self.technical_category_root_name)
        ]
        if len(direct_children_of_technical_root) == 1:
            return set(direct_children_of_technical_root)
        if len(direct_children_of_technical_root) > 1:
            raise Shopware5APIError(
                "Shopware5 category root 'Shopware > Italien' is ambiguous. "
                "Use --shop-id <SW5_SHOP_ID>."
            )
        if len(candidates) == 1:
            return set(candidates)
        if not candidates:
            raise Shopware5APIError("Shopware5 category root 'Italien' was not found.")
        raise Shopware5APIError(
            "Shopware5 category root 'Italien' is ambiguous. Use --shop-id <SW5_SHOP_ID>."
        )

    def _get_paged_rows(self, *, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            response = self.api_service.get(f"{path}?limit={self.page_size}&start={start}")
            batch = response.get("data") or []
            if not isinstance(batch, list):
                raise Shopware5APIError(f"Shopware5 returned an invalid {path} response.")
            batch = [row for row in batch if isinstance(row, dict)]
            rows.extend(batch)
            total = self._to_nonnegative_int(response.get("total"))
            if not batch or len(batch) < self.page_size or (total and len(rows) >= total):
                return rows
            start += len(batch)

    @classmethod
    def _italian_translation(
        cls,
        article: dict[str, Any],
        italian_shop_ids: set[str],
    ) -> dict[str, Any] | None:
        translations = article.get("translations") or []
        if isinstance(translations, dict):
            translations = [translations] if "shopId" in translations else list(translations.values())
        if not isinstance(translations, list):
            return None

        for translation in translations:
            if not isinstance(translation, dict):
                continue
            shop_id = cls._text(
                translation.get("shopId")
                or translation.get("shopID")
                or translation.get("languageId")
            )
            if shop_id in italian_shop_ids or cls._is_italian_locale(translation.get("locale")):
                return translation
        return None

    @classmethod
    def _apply_translation(cls, product: Product, translation: dict[str, Any]) -> list[str]:
        changed_fields: list[str] = []
        for source_field, target_field in cls.field_mapping.items():
            value = translation.get(source_field)
            if not cls._has_text(value) or getattr(product, target_field, None) == value:
                continue
            setattr(product, target_field, value)
            changed_fields.append(target_field)
        return changed_fields

    @classmethod
    def _is_italian_locale(cls, value: object) -> bool:
        if isinstance(value, dict):
            value = value.get("locale")
        return cls._text(value).lower().replace("-", "_") in cls.italian_locales

    @staticmethod
    def _has_text(value: object) -> bool:
        return value is not None and bool(str(value).strip())

    @staticmethod
    def _text(value: object) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalized_name(cls, value: object) -> str:
        return " ".join(cls._text(value).casefold().split())

    @staticmethod
    def _to_nonnegative_int(value: object) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
