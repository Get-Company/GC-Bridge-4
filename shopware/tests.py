from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from products.models import Image, Price, Product, ProductImage
from shopware.management.commands.shopware_sync_products import Command as ShopwareSyncProductsCommand
from shopware.management.commands.shopware_force_product_image_uploads import Command as ForceProductImageUploadsCommand
from shopware.models import ShopwareSettings
from shopware.services.order import OrderService
from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService
from shopware.services.shopware5 import Shopware5ProductSyncService
from shopware.services.shopware6 import Criteria, EqualsFilter, InvalidTokenError, Shopware6Service


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

    def test_request_post_strips_empty_criteria_values_recursively(self):
        client = MagicMock()
        client.request_post.return_value = {"ok": True}
        service = Shopware6Service.__new__(Shopware6Service)
        service.client = client

        criteria = Criteria(limit=10)
        criteria.associations["stateMachineState"] = Criteria()
        criteria.associations["orderCustomer"] = Criteria()
        criteria.associations["orderCustomer"].associations["customer"] = Criteria()
        criteria.filter.append(EqualsFilter(field="stateMachineState.technicalName", value="open"))

        result = service.request_post("/search/order", payload=criteria)

        self.assertEqual(result, {"ok": True})
        client.request_post.assert_called_once_with(
            "/search/order",
            payload={
                "limit": 10,
                "associations": {
                    "stateMachineState": {},
                    "orderCustomer": {
                        "associations": {
                            "customer": {},
                        },
                    },
                },
                "filter": [
                    {
                        "field": "stateMachineState.technicalName",
                        "value": "open",
                        "type": "equals",
                    },
                ],
            },
            additional_query_params=None,
        )


class Shopware5ProductSyncServiceTest(SimpleTestCase):
    def test_build_product_payload_updates_active_stock_factor_and_group_prices(self):
        price = SimpleNamespace(
            price=Decimal("10.00"),
            rebate_quantity=None,
            rebate_price=None,
            special_price=None,
            is_special_active=False,
            sales_channel=SimpleNamespace(is_default=True, is_active=True),
        )
        product = SimpleNamespace(
            erp_nr="581000",
            name="Mappe A4",
            description_short="Kurztext",
            description="Langtext.",
            is_active=False,
            purchase_unit=5,
            min_purchase=10,
            unit="% Stck",
            factor=3,
            storage=SimpleNamespace(get_stock=42),
            prefetched_prices_for_shopware_sync=[price],
        )

        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=MagicMock())
        payload = service.build_product_payload(product)

        self.assertFalse(payload["active"])
        self.assertEqual(payload["name"], "Mappe A4")
        self.assertEqual(payload["description"], "Kurztext")
        self.assertEqual(payload["descriptionLong"], "Langtext.")
        self.assertEqual(payload["mainDetail"]["inStock"], 42)
        self.assertEqual(payload["mainDetail"]["maxPurchase"], 10000)
        self.assertEqual(payload["mainDetail"]["minPurchase"], 10)
        self.assertEqual(payload["mainDetail"]["purchaseSteps"], 5)
        self.assertEqual(payload["mainDetail"]["packUnit"], "Stck")
        self.assertEqual(payload["mainDetail"]["gcFaktor"], 3)
        prices = payload["mainDetail"]["prices"]
        self.assertIn(
            {
                "customerGroupKey": "CHB2C",
                "from": 1,
                "to": "beliebig",
                "price": 13.0,
                "pseudoPrice": None,
            },
            prices,
        )
        self.assertIn(
            {
                "customerGroupKey": "IT_de",
                "from": 1,
                "to": "beliebig",
                "price": 10.45,
                "pseudoPrice": None,
            },
            prices,
        )

    def test_build_product_payload_uses_special_price_as_price_and_standard_as_pseudo_price(self):
        price = SimpleNamespace(
            price=Decimal("10.00"),
            rebate_quantity=None,
            rebate_price=None,
            special_price=Decimal("8.00"),
            is_special_active=True,
            sales_channel=SimpleNamespace(is_default=True, is_active=True),
        )
        product = SimpleNamespace(
            erp_nr="581000",
            is_active=True,
            purchase_unit=1,
            min_purchase=1,
            unit="Stck",
            factor=None,
            storage=SimpleNamespace(get_stock=5),
            prefetched_prices_for_shopware_sync=[price],
        )

        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=MagicMock())
        payload = service.build_product_payload(product)

        self.assertIn(
            {
                "customerGroupKey": "Vk0",
                "from": 1,
                "to": "beliebig",
                "price": 8.0,
                "pseudoPrice": 10.0,
            },
            payload["mainDetail"]["prices"],
        )


class Shopware5SyncProductsCommandTest(TestCase):
    @patch("shopware.management.commands.shopware5_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware5_sync_products.Shopware5ProductSyncService")
    def test_raises_command_error_when_batch_contains_errors(self, service_cls, runtime_start):
        Product.objects.create(erp_nr="581000", name="Mappe A4")
        runtime = MagicMock()
        runtime_start.return_value = runtime
        service_cls.return_value.sync_products.return_value = {
            "processed": 1,
            "success": 0,
            "errors": 1,
            "skipped": 0,
        }

        with self.assertRaisesMessage(CommandError, "Shopware5 Sync abgeschlossen mit 1 Fehler"):
            call_command("shopware5_sync_products", "581000", stdout=StringIO())

        runtime.close.assert_called_once()


class OrderServiceMicrotechWritebackTest(SimpleTestCase):
    def test_update_microtech_order_id_merges_existing_custom_fields(self):
        service = OrderService.__new__(OrderService)
        service.get_by_id = MagicMock(
            return_value={
                "data": [
                    {
                        "id": "order-1",
                        "customFields": {"existing": "keep"},
                    }
                ]
            }
        )
        service.request_patch = MagicMock(return_value={"ok": True})

        result = service.update_microtech_order_id(order_id="order-1", erp_order_id="WB26/324")

        self.assertEqual(result, {"ok": True})
        service.request_patch.assert_called_once_with(
            "/order/order-1",
            payload={
                "customFields": {
                    "existing": "keep",
                    "microtech_beleg_nr": "WB26/324",
                    "microtech_erp_order_id": "WB26/324",
                }
            },
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
        self.assertEqual(
            [relation["productId"] for relation in media_relations],
            ["shopware-product-6003", "shopware-product-6003"],
        )
        self.assertEqual([upload["file_name"] for upload in media_uploads], ["first.jpg", "later.jpg"])
        self.assertEqual(len(media_entities), 2)

    def test_media_payload_contains_all_product_media_relations(self):
        product = Product.objects.create(erp_nr="A-6004", sku="shopware-product-6004", name="Mehrere Bilder")
        images = [
            Image.objects.create(path="front.jpg"),
            Image.objects.create(path="detail.jpg"),
            Image.objects.create(path="packaging.jpg"),
        ]
        for order, image in enumerate(images, start=1):
            ProductImage.objects.create(product=product, image=image, order=order)

        media_relations, _media_entities, _media_uploads = ProductMediaSyncService().get_product_media_payload(
            product=product,
            product_id="shopware-product-6004",
        )

        self.assertEqual(len(media_relations), 3)
        self.assertEqual(
            [relation["productId"] for relation in media_relations],
            ["shopware-product-6004"] * 3,
        )
        self.assertEqual([relation["position"] for relation in media_relations], [1, 2, 3])


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
    def test_handle_replays_full_price_payload_after_fallback_sku_resolution(
        self,
        product_service_factory,
        mock_runtime_start,
    ):
        runtime = MagicMock()
        mock_runtime_start.return_value = runtime

        service = MagicMock()
        service.get_sku_map.side_effect = [{}, {"A-7004": "sku-4"}]
        product_service_factory.return_value = service

        default_channel = ShopwareSettings.objects.create(
            name="Default",
            is_active=True,
            is_default=True,
            currency_id="currency-default",
            rule_id_price="rule-default",
        )
        b2b_channel = ShopwareSettings.objects.create(
            name="B2B",
            is_active=True,
            currency_id="currency-b2b",
            rule_id_price="rule-b2b",
        )
        product = Product.objects.create(erp_nr="A-7004", name="Fallback Preisprodukt")
        Price.objects.create(product=product, sales_channel=default_channel, price=Decimal("10.00"))
        Price.objects.create(product=product, sales_channel=b2b_channel, price=Decimal("12.50"))

        cmd = ShopwareSyncProductsCommand()
        cmd.handle(erp_nrs=["A-7004"], all=False, limit=None, batch_size=10, only_with_images=False, log_images=False)

        self.assertEqual(service.bulk_upsert.call_count, 2)
        initial_fallback_payload = service.bulk_upsert.call_args_list[0].args[0][0]
        resolved_payload = service.bulk_upsert.call_args_list[1].args[0][0]

        self.assertNotIn("id", initial_fallback_payload)
        self.assertEqual(resolved_payload["id"], "sku-4")
        self.assertIn("price", resolved_payload)
        self.assertIn("prices", resolved_payload)
        self.assertEqual(
            [entry["ruleId"] for entry in resolved_payload["prices"]],
            ["rule-default", "rule-b2b"],
        )
        service.purge_product_prices_by_product_and_rule.assert_called_once_with(
            product_ids=["sku-4"],
            rule_ids=["rule-default", "rule-b2b"],
        )
        product.refresh_from_db()
        self.assertEqual(product.sku, "sku-4")
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
    @patch("shopware.management.commands.shopware_force_product_image_uploads.ProductService")
    def test_handle_processes_all_products_when_no_erp_numbers_are_given(self, product_service_factory):
        service = MagicMock()
        service.get_sku_map.return_value = {}
        service.purge_product_media_by_product_ids.return_value = 2
        product_service_factory.return_value = service

        first = Product.objects.create(erp_nr="A-5001", sku="sku-5001", shopware_image_sync_hash="hash-1")
        second = Product.objects.create(
            erp_nr="A-5002",
            sku="sku-5002",
            shopware_image_sync_hash="hash-2",
            is_active=False,
        )
        first_image = Image.objects.create(path="first-force.jpg")
        second_image = Image.objects.create(path="second-force.jpg")
        ProductImage.objects.create(product=first, image=first_image, order=1)
        ProductImage.objects.create(product=second, image=second_image, order=1)

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=False, limit=None, batch_size=10, erp_nrs=[], only_with_images=False, log_images=False)

        service.purge_product_media_by_product_ids.assert_called_once()
        self.assertEqual(
            service.purge_product_media_by_product_ids.call_args.kwargs["product_ids"],
            ["sku-5001", "sku-5002"],
        )
        self.assertEqual(service.upload_media_from_url.call_count, 2)
        self.assertEqual(service.bulk_upsert.call_count, 1)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertNotEqual(first.shopware_image_sync_hash, "hash-1")
        self.assertNotEqual(second.shopware_image_sync_hash, "hash-2")

    @patch("shopware.management.commands.shopware_force_product_image_uploads.ProductService")
    def test_handle_processes_only_selected_erp_numbers(self, product_service_factory):
        service = MagicMock()
        service.get_sku_map.return_value = {}
        service.purge_product_media_by_product_ids.return_value = 1
        product_service_factory.return_value = service

        target = Product.objects.create(erp_nr="A-5003", sku="sku-5003", shopware_image_sync_hash="hash-3")
        untouched = Product.objects.create(erp_nr="A-5004", shopware_image_sync_hash="hash-4")
        image = Image.objects.create(path="selected-force.jpg")
        ProductImage.objects.create(product=target, image=image, order=1)

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=False, limit=None, batch_size=10, erp_nrs=["A-5003"], only_with_images=False, log_images=False)

        target.refresh_from_db()
        untouched.refresh_from_db()
        self.assertNotEqual(target.shopware_image_sync_hash, "hash-3")
        self.assertEqual(untouched.shopware_image_sync_hash, "hash-4")
        service.purge_product_media_by_product_ids.assert_called_once()
        self.assertEqual(
            service.purge_product_media_by_product_ids.call_args.kwargs["product_ids"],
            ["sku-5003"],
        )

    @patch("shopware.management.commands.shopware_force_product_image_uploads.ProductService")
    def test_handle_collects_batch_errors_and_skips_assignment_after_upload_failure(self, product_service_factory):
        service = MagicMock()
        service.get_sku_map.return_value = {}
        service.purge_product_media_by_product_ids.return_value = 1
        service.upload_media_from_url.side_effect = RuntimeError("upload failed")
        product_service_factory.return_value = service

        product = Product.objects.create(erp_nr="A-5005", sku="sku-5005", shopware_image_sync_hash="hash-5")
        image = Image.objects.create(path="broken-force.jpg")
        ProductImage.objects.create(product=product, image=image, order=1)

        cmd = ForceProductImageUploadsCommand()
        with self.assertRaises(CommandError):
            cmd.handle(all=False, limit=None, batch_size=10, erp_nrs=[], only_with_images=False, log_images=False)

        service.purge_product_media_by_product_ids.assert_called_once()
        service.upload_media_from_url.assert_called_once()
        service.bulk_upsert.assert_not_called()
        product.refresh_from_db()
        self.assertEqual(product.shopware_image_sync_hash, "hash-5")
