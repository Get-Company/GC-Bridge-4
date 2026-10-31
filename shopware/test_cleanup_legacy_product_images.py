from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from shopware.management.commands.shopware_cleanup_legacy_product_images import Command
from shopware.services.product_media import ProductMediaSyncService


class CleanupLegacyProductImagesTest(SimpleTestCase):
    @patch("shopware.management.commands.shopware_cleanup_legacy_product_images.ProductService")
    @patch("shopware.management.commands.shopware_cleanup_legacy_product_images.Product.objects.filter")
    def test_removes_legacy_relation_only_after_webp_cover_and_asset_are_verified(self, filter_products, service_factory):
        image = SimpleNamespace(path="front.jpg", filename="front.jpg", url="https://assets.example/front.jpg")
        relation = SimpleNamespace(image=image, order=1)
        product = SimpleNamespace(
            erp_nr="A-1", sku="product-1", get_ordered_product_images=lambda: [relation],
        )
        media_service = ProductMediaSyncService()
        product.shopware_image_sync_hash = media_service.build_media_sync_hash(product=product)
        webp_id = media_service.build_media_id("webp:front.jpg")
        old_id = media_service.build_media_id("front.jpg")
        cover_id = media_service.build_product_media_id(product_id=product.sku, media_id=webp_id)
        filter_products.return_value.distinct.return_value.order_by.return_value.prefetch_related.return_value = [product]

        service = service_factory.return_value
        service.product_media_base_path = "/product-media"
        service.get.return_value = {"data": {"attributes": {"coverId": cover_id}}}
        service._entity_field.side_effect = lambda row, field: row.get("attributes", {}).get(field, "")
        service.find_product_media_rows_by_product_ids.return_value = [
            {"id": cover_id, "media_id": webp_id},
            {"id": "old-relation", "media_id": old_id},
        ]
        service.find_media_by_ids.side_effect = [
            {webp_id: {"extension": "webp"}},
            {old_id: {"extension": "jpg"}},
        ]

        Command().handle(erp_nrs=[], limit=None, apply=True, delete_orphans=False)

        service.request_delete.assert_called_once_with("/product-media/old-relation")
        service.delete_media_by_ids.assert_not_called()

    @patch("shopware.management.commands.shopware_cleanup_legacy_product_images.ProductService")
    @patch("shopware.management.commands.shopware_cleanup_legacy_product_images.Product.objects.filter")
    def test_keeps_legacy_relation_when_webp_cover_is_not_active(self, filter_products, service_factory):
        image = SimpleNamespace(path="front.jpg", filename="front.jpg", url="https://assets.example/front.jpg")
        product = SimpleNamespace(
            erp_nr="A-1", sku="product-1",
            get_ordered_product_images=lambda: [SimpleNamespace(image=image, order=1)],
        )
        media_service = ProductMediaSyncService()
        product.shopware_image_sync_hash = media_service.build_media_sync_hash(product=product)
        webp_id = media_service.build_media_id("webp:front.jpg")
        cover_id = media_service.build_product_media_id(product_id=product.sku, media_id=webp_id)
        filter_products.return_value.distinct.return_value.order_by.return_value.prefetch_related.return_value = [product]

        service = service_factory.return_value
        service.find_product_media_rows_by_product_ids.return_value = [{"id": cover_id, "media_id": webp_id}]
        service.get.return_value = {"data": {"attributes": {"coverId": "different-cover"}}}
        service._entity_field.side_effect = lambda row, field: row.get("attributes", {}).get(field, "")

        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            Command().handle(erp_nrs=[], limit=None, apply=True, delete_orphans=False)

        service.request_delete.assert_not_called()
