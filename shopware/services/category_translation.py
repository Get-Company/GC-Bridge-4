from __future__ import annotations

from core.services import BaseService
from products.models import Category
from shopware.services.product import ProductService
from shopware.services.translations import ShopwareTranslationService


class ShopwareCategoryTranslationSyncService(BaseService):
    """Write customer-visible category translations back to Shopware 6 only."""

    model = Category

    def __init__(self, *, product_service: ProductService | None = None) -> None:
        self.product_service = product_service or ProductService()
        self.translation_service = ShopwareTranslationService()

    def sync(self, category: Category) -> bool:
        """Upsert the native translations for one existing Shopware category."""
        category_id = str(category.sw6_id or "").strip()
        if not category_id:
            return False

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
        if not translations:
            return False

        self.product_service.bulk_upsert(
            [{"id": category_id, "translations": translations}],
            entity_name="category",
        )
        return True
