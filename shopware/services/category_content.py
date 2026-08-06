from __future__ import annotations

from collections.abc import Iterable

from core.services import BaseService
from products.models import Category, Product
from shopware.services.product import ProductService
from shopware.services.translations import ShopwareTranslationService


class ShopwareCategoryContentSyncService(BaseService):
    """Synchronize one local category, its translations, and direct product assignments."""

    model = Category

    def __init__(
        self,
        *,
        product_service: ProductService | None = None,
        translation_service: ShopwareTranslationService | None = None,
    ) -> None:
        self.product_service = product_service or ProductService()
        self.translation_service = translation_service or ShopwareTranslationService()

    def sync(self, category: Category) -> dict[str, int | str]:
        """Write the customer-visible category content and make its product set exact."""
        category_id = str(category.sw6_id or "").strip()
        if not category_id:
            return {"status": "skipped", "created_assignments": 0, "removed_assignments": 0}

        translations = self.translation_service.build_translations(
            instance=category,
            field_mapping={
                "name": "name",
                "description": "description",
                "meta_title": "metaTitle",
                "meta_description": "metaDescription",
                "meta_keywords": "keywords",
            },
            translation_language_ids=self.translation_service.language_ids_for(self.product_service),
        )
        payload = {
            "id": category_id,
            "name": str(category.name or "").strip(),
            "description": str(category.description or ""),
            "metaTitle": str(category.meta_title or ""),
            "metaDescription": str(category.meta_description or ""),
            "keywords": str(category.meta_keywords or ""),
            "active": bool(category.is_active),
            "visible": bool(category.is_visible),
        }
        if translations:
            payload["translations"] = translations
        self.product_service.bulk_upsert([payload], entity_name="category")

        desired_product_ids = self._product_ids(category)
        existing_product_ids = self.product_service.get_product_ids_in_category(category_id)
        new_product_ids = desired_product_ids - existing_product_ids
        stale_product_ids = existing_product_ids - desired_product_ids
        if new_product_ids:
            self.product_service.bulk_upsert_product_categories(
                self._assignment_payload(category_id, new_product_ids)
            )
        if stale_product_ids:
            self.product_service.bulk_delete_product_categories(
                self._assignment_payload(category_id, stale_product_ids)
            )

        return {
            "status": "succeeded",
            "created_assignments": len(new_product_ids),
            "removed_assignments": len(stale_product_ids),
        }

    @staticmethod
    def _product_ids(category: Category) -> set[str]:
        """Return Shopware IDs of every local product assigned to ``category``."""
        return {
            str(product_id).strip()
            for product_id in Product.categories.through.objects.filter(category_id=category.pk)
            .values_list("product__sku", flat=True)
            if str(product_id or "").strip()
        }

    @staticmethod
    def _assignment_payload(category_id: str, product_ids: Iterable[str]) -> list[dict[str, str]]:
        return [
            {"productId": product_id, "categoryId": category_id}
            for product_id in sorted({str(value).strip() for value in product_ids if str(value).strip()})
        ]
