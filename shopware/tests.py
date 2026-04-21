from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from products.models import Image, Product, ProductImage
from shopware.management.commands.shopware_sync_products import Command as ShopwareSyncProductsCommand
from shopware.management.commands.shopware_force_product_image_uploads import Command as ForceProductImageUploadsCommand
from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService
from shopware.services.shopware6 import InvalidTokenError, Shopware6Service


class Shopware6ServiceTokenRetryTest(SimpleTestCase):
    @patch("shopware.services.shopware6.Shopware6AdminAPIClientBase")
    def test_request_post_retries_once_on_invalid_token(self, client_factory):
        first_client = MagicMock()
        second_client = MagicMock()
        first_client.request_post.side_effect = InvalidTokenError()
        second_client.request_post.return_value = {"ok": True}
        client_factory.side_effect = [first_client, second_client]

        service = Shopware6Service()
        result = service.request_post("/search/product", payload={"limit": 1})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client_factory.call_count, 2)
        first_client.request_post.assert_called_once_with(
            "/search/product",
            payload={"limit": 1},
            additional_query_params=None,
        )
        second_client.request_post.assert_called_once_with(
            "/search/product",
            payload={"limit": 1},
            additional_query_params=None,
        )


class ProductMediaSyncServiceTest(SimpleTestCase):
    @patch.object(ProductService, "request_post")
    def test_get_sku_map_reads_product_number_from_top_level_response(self, mock_request_post):
        service = ProductService.__new__(ProductService)
        service.search_path = "/search/product"
        mock_request_post.return_value = {
            "data": [
                {
                    "id": "shopware-product-900001",
                    "productNumber": "900001",
                }
            ]
        }

        result = ProductService.get_sku_map(service, ["900001"])

        self.assertEqual(result, {"900001": "shopware-product-900001"})
        mock_request_post.assert_called_once_with(
            "/search/product",
            payload={
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "productNumber",
                        "value": "900001",
                    }
                ],
                "limit": 1,
            },
        )

    @patch.object(ProductService, "get_by_number")
    @patch.object(ProductService, "request_post")
    def test_get_sku_map_retries_missing_product_numbers_with_single_lookup(
        self,
        mock_request_post,
        mock_get_by_number,
    ):
        service = ProductService.__new__(ProductService)
        service.search_path = "/search/product"
        mock_request_post.return_value = {"data": []}
        mock_get_by_number.return_value = {
            "data": [
                {
                    "id": "shopware-product-900002",
                    "productNumber": "900002",
                }
            ]
        }

        result = ProductService.get_sku_map(service, ["900002"])

        self.assertEqual(result, {"900002": "shopware-product-900002"})
        mock_get_by_number.assert_called_once_with("900002", limit=1)

    def test_split_file_name_extracts_base_name_and_extension(self):
        base_name, extension = ProductMediaSyncService.split_file_name("produkt-bild.JPEG")

        self.assertEqual(base_name, "produkt-bild")
        self.assertEqual(extension, "jpeg")

    @patch.object(ProductService, "request_post")
    def test_upload_media_from_url_uses_shopware_upload_endpoint(self, mock_request_post):
        service = ProductService.__new__(ProductService)
        service.delete_conflicting_media_by_filename = MagicMock(return_value=0)

        ProductService.upload_media_from_url(
            service,
            media_id="media-1",
            file_name="bild.png",
            source_url="https://cdn.example.com/img/bild.png",
        )

        mock_request_post.assert_called_once_with(
            "/_action/media/media-1/upload",
            payload={"url": "https://cdn.example.com/img/bild.png"},
            additional_query_params={"extension": "png", "fileName": "bild"},
        )

    @patch.object(ProductService, "request_post")
    def test_upload_media_from_url_retries_after_duplicate_filename_conflict(self, mock_request_post):
        service = ProductService.__new__(ProductService)
        service.delete_conflicting_media_by_filename = MagicMock(return_value=1)
        mock_request_post.side_effect = [
            RuntimeError("Shopware request failed (409): CONTENT__MEDIA_DUPLICATED_FILE_NAME"),
            {"ok": True},
        ]

        result = ProductService.upload_media_from_url(
            service,
            media_id="media-2",
            file_name="bild.jpg",
            source_url="https://cdn.example.com/img/bild.jpg",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(service.delete_conflicting_media_by_filename.call_count, 2)
        mock_request_post.assert_called_with(
            "/_action/media/media-2/upload",
            payload={"url": "https://cdn.example.com/img/bild.jpg"},
            additional_query_params={"extension": "jpg", "fileName": "bild"},
        )

    @patch.object(ProductService, "request_delete")
    @patch.object(ProductService, "request_post")
    def test_delete_conflicting_media_by_filename_removes_other_media_ids(self, mock_request_post, mock_request_delete):
        service = ProductService.__new__(ProductService)
        mock_request_post.return_value = {
            "data": [
                {"id": "media-1"},
                {"id": "media-2"},
            ]
        }

        deleted = ProductService.delete_conflicting_media_by_filename(
            service,
            file_name="bild",
            extension="jpg",
            exclude_media_id="media-1",
        )

        self.assertEqual(deleted, 1)
        mock_request_post.assert_called_once_with(
            "/search/media",
            payload={
                "filter": [
                    {"type": "equals", "field": "fileName", "value": "bild"},
                    {"type": "equals", "field": "fileExtension", "value": "jpg"},
                ],
                "limit": 50,
            },
        )
        mock_request_delete.assert_called_once_with("/media/media-2")


class ProductMediaSyncHashRegressionTest(TestCase):
    def test_hash_stays_stable_when_only_updated_at_changes(self):
        product = Product.objects.create(erp_nr="A-6001", sku="shopware-product-6001", name="Hash Stabil")
        image = Image.objects.create(path="stable-cover.jpg")
        product_image = ProductImage.objects.create(product=product, image=image, order=1)

        first_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        product_image.updated_at = timezone.now()
        product_image.save(update_fields=["updated_at"])
        product.refresh_from_db()
        second_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        self.assertEqual(first_hash, second_hash)

    def test_hash_changes_when_image_order_changes(self):
        product = Product.objects.create(erp_nr="A-6002", sku="shopware-product-6002", name="Hash Reihenfolge")
        first = Image.objects.create(path="first-cover.jpg")
        second = Image.objects.create(path="second-cover.jpg")
        first_relation = ProductImage.objects.create(product=product, image=first, order=1)
        second_relation = ProductImage.objects.create(product=product, image=second, order=2)

        first_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        first_relation.order = 2
        first_relation.save(update_fields=["order"])
        second_relation.order = 1
        second_relation.save(update_fields=["order"])
        product.refresh_from_db()
        second_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        self.assertNotEqual(first_hash, second_hash)

    def test_media_payload_follows_product_image_order(self):
        product = Product.objects.create(erp_nr="A-6003", sku="shopware-product-6003", name="Payload Reihenfolge")
        later = Image.objects.create(path="later.jpg")
        first = Image.objects.create(path="first.jpg")
        ProductImage.objects.create(product=product, image=later, order=2)
        ProductImage.objects.create(product=product, image=first, order=1)

        media_relations, media_entities, media_uploads = ProductMediaSyncService().get_product_media_payload(
            product=product,
            product_id="shopware-product-6003",
        )

        self.assertEqual([relation["position"] for relation in media_relations], [1, 2])
        self.assertEqual([upload["file_name"] for upload in media_uploads], ["first.jpg", "later.jpg"])
        self.assertEqual(len(media_entities), 2)


class ShopwareSyncProductsCommandBatchTest(TestCase):
    @patch("shopware.management.commands.shopware_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware_sync_products.ProductService")
    def test_handle_separates_missing_sku_products_from_main_upsert_batch(
        self,
        product_service_factory,
        mock_runtime_start,
    ):
        runtime = MagicMock()
        mock_runtime_start.return_value = runtime

        service = MagicMock()
        service.get_sku_map.return_value = {}
        product_service_factory.return_value = service

        Product.objects.create(erp_nr="A-7001", sku="sku-1", name="Mit SKU")
        Product.objects.create(erp_nr="A-7002", name="Ohne SKU")

        cmd = ShopwareSyncProductsCommand()
        cmd.handle(erp_nrs=[], all=True, limit=2, batch_size=10, only_with_images=False, log_images=False)

        self.assertEqual(service.bulk_upsert.call_count, 2)
        main_payloads = service.bulk_upsert.call_args_list[0].args[0]
        fallback_payloads = service.bulk_upsert.call_args_list[1].args[0]

        self.assertEqual([payload["productNumber"] for payload in main_payloads], ["A-7001"])
        self.assertEqual(main_payloads[0]["id"], "sku-1")
        self.assertEqual([payload["productNumber"] for payload in fallback_payloads], ["A-7002"])
        self.assertNotIn("id", fallback_payloads[0])
        runtime.close.assert_called_once()

    @patch("shopware.management.commands.shopware_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware_sync_products.ProductService")
    def test_handle_uses_erp_number_as_name_fallback_when_product_name_is_blank(
        self,
        product_service_factory,
        mock_runtime_start,
    ):
        runtime = MagicMock()
        mock_runtime_start.return_value = runtime

        service = MagicMock()
        service.get_sku_map.return_value = {}
        product_service_factory.return_value = service

        Product.objects.create(erp_nr="A-7003", sku="sku-3", name=None, name_de=None, name_en=None)

        cmd = ShopwareSyncProductsCommand()
        cmd.handle(erp_nrs=["A-7003"], all=False, limit=None, batch_size=10, only_with_images=False, log_images=False)

        payloads = service.bulk_upsert.call_args.args[0]
        self.assertEqual(payloads[0]["name"], "A-7003")
        runtime.close.assert_called_once()


class ForceProductImageUploadsCommandTest(TestCase):
    @patch("shopware.management.commands.shopware_force_product_image_uploads.call_command")
    def test_handle_resets_hashes_and_runs_shopware_sync_for_all(self, mock_call_command):
        Product.objects.create(erp_nr="A-5001", shopware_image_sync_hash="hash-1")
        Product.objects.create(erp_nr="A-5002", shopware_image_sync_hash="hash-2")

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=True, limit=25, batch_size=10, erp_nrs=[], only_with_images=False, log_images=False)

        self.assertEqual(Product.objects.exclude(shopware_image_sync_hash="").count(), 0)
        mock_call_command.assert_called_once_with(
            "shopware_sync_products",
            all=True,
            limit=25,
            batch_size=10,
            only_with_images=False,
            log_images=False,
        )

    @patch("shopware.management.commands.shopware_force_product_image_uploads.call_command")
    def test_handle_resets_selected_hashes_and_runs_shopware_sync_for_selection(self, mock_call_command):
        target = Product.objects.create(erp_nr="A-5003", shopware_image_sync_hash="hash-3")
        untouched = Product.objects.create(erp_nr="A-5004", shopware_image_sync_hash="hash-4")

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=False, limit=None, batch_size=50, erp_nrs=["A-5003"], only_with_images=False, log_images=False)

        target.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(target.shopware_image_sync_hash, "")
        self.assertEqual(untouched.shopware_image_sync_hash, "hash-4")
        mock_call_command.assert_called_once_with(
            "shopware_sync_products",
            "A-5003",
            limit=None,
            batch_size=50,
            only_with_images=False,
            log_images=False,
        )

    @patch("shopware.management.commands.shopware_force_product_image_uploads.call_command")
    def test_handle_only_with_images_filters_reset_queryset_and_passes_flags(self, mock_call_command):
        with_image = Product.objects.create(erp_nr="A-5005", shopware_image_sync_hash="hash-5")
        without_image = Product.objects.create(erp_nr="A-5006", shopware_image_sync_hash="hash-6")
        image = Image.objects.create(path="batch-cover.jpg")
        ProductImage.objects.create(product=with_image, image=image, order=1)

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=True, limit=10, batch_size=10, erp_nrs=[], only_with_images=True, log_images=True)

        with_image.refresh_from_db()
        without_image.refresh_from_db()
        self.assertEqual(with_image.shopware_image_sync_hash, "")
        self.assertEqual(without_image.shopware_image_sync_hash, "hash-6")
        mock_call_command.assert_called_once_with(
            "shopware_sync_products",
            all=True,
            limit=10,
            batch_size=10,
            only_with_images=True,
            log_images=True,
        )

    def test_handle_requires_selection_or_all(self):
        cmd = ForceProductImageUploadsCommand()

        with self.assertRaises(CommandError):
            cmd.handle(all=False, limit=None, batch_size=50, erp_nrs=[], only_with_images=False, log_images=False)
