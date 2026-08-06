from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote, urlencode

from loguru import logger

from core.services import BaseService
from products.models import Product

from .shopware5 import Shopware5APIError, Shopware5ProductSyncService


class Shopware5ItalianTranslationImportService(BaseService):
    """Importiert vorhandene italienische Artikeltexte aus Shopware 5 nach Django."""

    model = Product
    italian_locales = {"it_it"}
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
        italian_shop_id = self._italian_shop_id(italian_shop_id=italian_shop_id)
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
                    italian_shop_id=italian_shop_id,
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
        italian_shop_id: str,
        dry_run: bool = False,
    ) -> str:
        product_number = str(product.erp_nr or "").strip()
        if not product_number:
            raise ValueError("Product has no ERP number.")

        article = self.api_service.get_article_by_number(product_number)
        article_id = self._text(article.get("id"))
        if not article_id:
            raise Shopware5APIError(f"Shopware5 article id missing for {product_number}.")
        translation = self._article_translation(article_id=article_id, shop_id=italian_shop_id)
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

    def available_shops(self) -> list[dict[str, str]]:
        """Return Shopware5 shops with detail data for safe manual shop selection."""
        self._validate_api_config()
        result: list[dict[str, str]] = []
        for shop in self._get_paged_rows(path="/shops"):
            shop_id = self._text(shop.get("id"))
            if not shop_id:
                continue
            response = self.api_service.get(f"/shops/{quote(shop_id, safe='')}")
            detail = response.get("data") or {}
            if not isinstance(detail, dict):
                raise Shopware5APIError(f"Shopware5 shop {shop_id} returned invalid detail data.")
            result.append(
                {
                    "id": shop_id,
                    "name": self._text(detail.get("name") or shop.get("name")),
                    "category_id": self._text(detail.get("categoryId") or shop.get("categoryId")),
                    "locale": self._locale_code(detail.get("locale") or shop.get("locale")),
                }
            )
        return result

    def _italian_shop_id(self, *, italian_shop_id: str | None = None) -> str:
        explicit_shop_id = self._text(italian_shop_id)
        if explicit_shop_id:
            return explicit_shop_id

        shops = self._get_paged_rows(path="/shops")
        italian_shop_ids = []
        for shop in shops:
            shop_id = self._text(shop.get("id"))
            if not shop_id:
                continue
            response = self.api_service.get(f"/shops/{quote(shop_id, safe='')}")
            shop_detail = response.get("data") or {}
            if not isinstance(shop_detail, dict):
                raise Shopware5APIError(f"Shopware5 shop {shop_id} returned invalid detail data.")
            locale = shop_detail.get("locale") or shop.get("locale")
            if self._is_italian_locale(locale):
                italian_shop_ids.append(shop_id)

        if len(italian_shop_ids) == 1:
            return italian_shop_ids[0]
        if len(italian_shop_ids) > 1:
            raise Shopware5APIError(
                "More than one Italian Shopware5 language shop with locale it_IT was found. "
                "Use --shop-id <SW5_SHOP_ID> to select the source shop explicitly."
            )
        raise Shopware5APIError(
            "No Italian Shopware5 language shop with locale it_IT was found. "
            "Use --shop-id <SW5_SHOP_ID> to select the source shop explicitly."
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

    def _article_translation(self, *, article_id: str, shop_id: str) -> dict[str, Any] | None:
        query = urlencode(
            {
                "limit": 1,
                "filter[0][property]": "translation.shopId",
                "filter[0][value]": shop_id,
                "filter[1][property]": "translation.key",
                "filter[1][value]": article_id,
                "filter[2][property]": "translation.type",
                "filter[2][value]": "article",
            }
        )
        response = self.api_service.get(f"/translations?{query}")
        translations = response.get("data") or []
        if not isinstance(translations, list):
            raise Shopware5APIError("Shopware5 returned an invalid translations response.")

        for translation in translations:
            if not isinstance(translation, dict):
                continue
            data = translation.get("data")
            if isinstance(data, dict):
                return data
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
        return cls._locale_code(value).lower().replace("-", "_") in cls.italian_locales

    @classmethod
    def _locale_code(cls, value: object) -> str:
        if isinstance(value, dict):
            value = value.get("locale")
        return cls._text(value)

    @staticmethod
    def _has_text(value: object) -> bool:
        return value is not None and bool(str(value).strip())

    @staticmethod
    def _text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _to_nonnegative_int(value: object) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
