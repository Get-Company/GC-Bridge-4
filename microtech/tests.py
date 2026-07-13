from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from microtech.management.commands.microtech_sync_products import Command as MicrotechSyncProductsCommand
from microtech.management.commands.microtech_update_prices import Command as MicrotechUpdatePricesCommand
from microtech.management.commands.microtech_update_product import Command as MicrotechUpdateProductCommand
from microtech.services.base import MicrotechDatasetService
from microtech.services.artikel import MicrotechArtikelService
from microtech.services.graphql_client import MicrotechGraphQLClientService
from microtech.services.product_payload import MicrotechProductPayloadService
from products.models import Price, Product, ProductImage, Tax
from shopware.models import ShopwareSettings


class _FakeGraphQLClient(MicrotechGraphQLClientService):
    def __init__(self, product_result):
        self.request_product = MagicMock(return_value=product_result)


class MicrotechArtikelServiceProductJobTest(SimpleTestCase):
    def test_range_request_uses_graphql_filter_string(self):
        client = _FakeGraphQLClient({})
        service = MicrotechArtikelService(erp=client)
        service.set_range(from_range="091300", to_range="091399", field="Nr")
        service.set_filter({"WBSHpKZ": 1})

        request = service._build_request(index_field="Nr")

        self.assertEqual(request["dataset"], "Artikel")
        self.assertEqual(request["indexField"], "Nr")
        self.assertEqual(request["range"], {"fromValues": ["091300"], "toValues": ["091399"]})
        self.assertEqual(request["filter"], "WBSHpKZ = 1")
        self.assertNotIn("filters", request)

    def test_find_uses_request_product_and_maps_product_job_result(self):
        client = _FakeGraphQLClient({
            "status": "DONE",
            "product": {
                "erpNumber": "091300",
                "name": "Graph Produkt",
                "description": "Langtext",
                "descriptionShort": "Kurztext",
                "isActive": True,
                "factor": 1,
                "unit": "Stk",
                "minPurchase": 2,
                "purchaseUnit": 1,
                "sortOrder": 10,
                "price": "12.95",
                "rebateQuantity": 5,
                "rebatePrice": "11.95",
                "specialPrice": "9.95",
                "specialStartDate": "2026-05-01",
                "specialEndDate": "2026-05-31",
                "taxKey": "M19",
                "taxRate": "19.00",
                "customsTariffNumber": "48203000",
                "weightGrossKg": "1.25",
                "weightNetKg": "1.00",
                "warehouseNumber": 3,
                "stock": 7,
                "storageLocation": "A1",
                "images": ["https://cdn.example.test/img/first.jpg", {"fileName": "second.png"}],
            },
        })
        service = MicrotechArtikelService(erp=client)

        self.assertTrue(service.find("091300"))

        client.request_product.assert_called_once_with("091300")
        self.assertEqual(service.get_erp_nr(), "091300")
        self.assertEqual(service.get_name(), "Graph Produkt")
        self.assertEqual(service.get_description_short(), "Kurztext")
        self.assertTrue(service.get_is_active())
        self.assertEqual(service.get_price(), "12.95")
        self.assertEqual(service.get_tax_rate(), Decimal("19.00"))
        self.assertEqual(service.get_customs_tariff_number(), "48203000")
        self.assertEqual(service.get_weight_gross(), Decimal("1.25"))
        self.assertEqual(service.get_weight_net(), Decimal("1.00"))
        self.assertEqual(service.get_warehouse_number(), 3)
        self.assertEqual(service.get_stock(), 7)
        self.assertEqual(service.get_storage_location(), "A1")
        self.assertEqual(service.get_image_list(), ["first.jpg", "second.png"])


class MicrotechProductPayloadServiceTest(SimpleTestCase):
    def test_duplicate_vk0_prices_to_vk1_writes_vk0_and_vk1_price_trees(self):
        payload = {
            "name": "Artikel",
            "price": "10,25",
            "rebateQuantity": 5,
            "rebatePrice": "9,25",
            "specialPrice": "",
            "specialStartDate": "",
            "specialEndDate": "",
        }

        result = MicrotechProductPayloadService.duplicate_vk0_prices_to_vk1(payload)

        self.assertNotIn("price", result)
        self.assertNotIn("rebateQuantity", result)
        self.assertNotIn("rebatePrice", result)
        self.assertNotIn("specialPrice", result)
        self.assertEqual(
            result["priceTrees"],
            [
                {
                    "tree": "Vk0",
                    "price": "10,25",
                    "rebateQuantity": 5,
                    "rebatePrice": "9,25",
                    "specialPrice": "",
                    "specialStartDate": "",
                    "specialEndDate": "",
                },
                {
                    "tree": "Vk1",
                    "price": "10,25",
                    "rebateQuantity": 5,
                    "rebatePrice": "9,25",
                    "specialPrice": "",
                    "specialStartDate": "",
                    "specialEndDate": "",
                }
            ],
        )
        self.assertNotIn("priceTrees", payload)


class MicrotechSyncProductsCommandTest(TestCase):
    def setUp(self):
        self.tax_19 = Tax.objects.create(
            name="MwSt 19",
            rate=Decimal("19.00"),
            shopware_id="tax-19",
        )
        self.tax_7 = Tax.objects.create(
            name="MwSt 7",
            rate=Decimal("7.00"),
            shopware_id="tax-7",
        )
        self.default_channel = ShopwareSettings.objects.create(
            name="Default",
            is_default=True,
            is_active=True,
        )

    @staticmethod
    def _build_artikel_service(*, erp_nr: str, is_active: bool):
        artikel_service = MagicMock()
        artikel_service.get_erp_nr.return_value = erp_nr
        artikel_service.get_name.return_value = "Testartikel"
        artikel_service.get_factor.return_value = None
        artikel_service.get_is_active.return_value = 1 if is_active else 0
        artikel_service.get_unit.return_value = "Stk"
        artikel_service.get_min_purchase.return_value = None
        artikel_service.get_purchase_unit.return_value = None
        artikel_service.get_description.return_value = "Beschreibung"
        artikel_service.get_description_short.return_value = "Kurz"
        artikel_service.get_sort_order.return_value = None
        artikel_service.get_tax_rate.return_value = Decimal("19.00")
        artikel_service.get_price.return_value = None
        artikel_service.get_rebate_quantity.return_value = None
        artikel_service.get_rebate_price.return_value = None
        artikel_service.get_special_price.return_value = None
        artikel_service.get_special_start_date.return_value = None
        artikel_service.get_special_end_date.return_value = None
        artikel_service.get_image_list.return_value = []
        artikel_service.get_customs_tariff_number.return_value = ""
        artikel_service.get_weight_gross.return_value = None
        artikel_service.get_weight_net.return_value = None
        # MagicMock besteht jeden hasattr-Check; ohne diese Stubs würde der
        # Inline-Stock-Pfad statt des Lager-Fallbacks genommen.
        artikel_service.get_stock.return_value = None
        artikel_service.get_storage_location.return_value = None
        artikel_service.get_warehouse_number.return_value = None
        return artikel_service

    @staticmethod
    def _build_lager_service():
        lager_service = MagicMock()
        lager_service.get_stock_and_location.return_value = (5, "A1")
        return lager_service

    def test_sync_preserves_is_active_for_existing_product_when_flag_enabled(self):
        product = Product.objects.create(
            erp_nr="1000",
            name="Bestehend",
            is_active=False,
        )
        cmd = MicrotechSyncProductsCommand()
        cmd._sync_current_record(
            self._build_artikel_service(erp_nr=product.erp_nr, is_active=True),
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=True,
        )

        product.refresh_from_db()
        self.assertFalse(product.is_active)

    def test_sync_stores_images_in_microtech_order(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1001", is_active=True)
        artikel_service.get_image_list.return_value = ["second.png", "first.jpg", "second.png"]

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        product = Product.objects.get(erp_nr="1001")
        self.assertEqual(list(product.images.order_by("path").values_list("path", flat=True)), ["first.jpg", "second.png"])
        self.assertEqual(
            list(
                ProductImage.objects.filter(product=product)
                .order_by("order")
                .values_list("image__path", flat=True)
            ),
            ["second.png", "first.jpg"],
        )
        self.assertEqual([image.path for image in product.get_images()], ["second.png", "first.jpg"])

    def test_sync_prefers_lager_stock_over_product_job_stock(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1008", is_active=True)
        artikel_service.get_stock.return_value = "12"
        artikel_service.get_storage_location.return_value = "B2"
        lager_service = self._build_lager_service()

        cmd._sync_current_record(
            artikel_service,
            lager_service,
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        storage = Product.objects.get(erp_nr="1008").storage
        self.assertEqual(storage.stock, 5)
        self.assertEqual(storage.location, "A1")
        lager_service.get_stock_and_location.assert_called_once_with(art_nr="1008")

    def test_sync_uses_lager_stock_when_product_job_stock_is_empty(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1009", is_active=True)
        lager_service = self._build_lager_service()

        cmd._sync_current_record(
            artikel_service,
            lager_service,
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        storage = Product.objects.get(erp_nr="1009").storage
        self.assertEqual(storage.stock, 5)
        self.assertEqual(storage.location, "A1")
        lager_service.get_stock_and_location.assert_called_once_with(art_nr="1009")

    def test_sync_uses_product_warehouse_for_lager_lookup(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1010", is_active=True)
        artikel_service.get_warehouse_number.return_value = 3
        lager_service = self._build_lager_service()

        cmd._sync_current_record(
            artikel_service,
            lager_service,
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        lager_service.get_stock_and_location.assert_called_once_with(art_nr="1010", lager_nr=3)

    def test_sync_preserves_microtech_special_price_without_percentage(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1002", is_active=True)
        artikel_service.get_price.return_value = Decimal("100.00")
        artikel_service.get_special_price.return_value = Decimal("79.95")
        artikel_service.get_special_start_date.return_value = timezone.now() - timedelta(days=2)
        artikel_service.get_special_end_date.return_value = timezone.now() + timedelta(days=2)

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        product = Product.objects.get(erp_nr="1002")
        price = Price.objects.get(product=product, sales_channel__is_default=True)

        self.assertIsNone(price.special_percentage)
        self.assertEqual(price.special_price, Decimal("79.95"))
        self.assertTrue(price.is_special_active)

    def test_sync_same_microtech_price_values_do_not_create_additional_history_entry(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1003", is_active=True)
        artikel_service.get_price.return_value = Decimal("100.00")
        artikel_service.get_rebate_quantity.return_value = 10
        artikel_service.get_rebate_price.return_value = Decimal("95.00")

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        product = Product.objects.get(erp_nr="1003")
        price = Price.objects.get(product=product, sales_channel__is_default=True)
        initial_history_count = price.history_entries.count()

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        price.refresh_from_db()
        self.assertEqual(price.history_entries.count(), initial_history_count)

    def test_sync_special_only_change_does_not_create_additional_history_entry(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1004", is_active=True)
        artikel_service.get_price.return_value = Decimal("100.00")
        artikel_service.get_rebate_quantity.return_value = 10
        artikel_service.get_rebate_price.return_value = Decimal("95.00")

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        product = Product.objects.get(erp_nr="1004")
        price = Price.objects.get(product=product, sales_channel__is_default=True)
        initial_history_count = price.history_entries.count()

        artikel_service.get_special_price.return_value = Decimal("79.95")
        artikel_service.get_special_start_date.return_value = timezone.now() - timedelta(days=2)
        artikel_service.get_special_end_date.return_value = timezone.now() + timedelta(days=2)

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        price.refresh_from_db()
        self.assertEqual(price.special_price, Decimal("79.95"))
        self.assertEqual(price.history_entries.count(), initial_history_count)

    def test_sync_changed_rebate_quantity_writes_history_entry(self):
        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1005", is_active=True)
        artikel_service.get_price.return_value = Decimal("100.00")
        artikel_service.get_rebate_quantity.return_value = 10
        artikel_service.get_rebate_price.return_value = Decimal("95.00")

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        product = Product.objects.get(erp_nr="1005")
        price = Price.objects.get(product=product, sales_channel__is_default=True)

        artikel_service.get_rebate_quantity.return_value = 20

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        latest_history = price.history_entries.order_by("-created_at", "-id").first()
        self.assertEqual(price.history_entries.count(), 2)
        self.assertIsNotNone(latest_history)
        self.assertEqual(latest_history.changed_fields, "rebate_quantity")
        self.assertEqual(latest_history.rebate_quantity, 20)

    def test_sync_preserves_existing_non_default_channel_prices(self):
        b2b_channel = ShopwareSettings.objects.create(
            name="B2B",
            is_active=True,
            price_factor=Decimal("1.25"),
        )
        product = Product.objects.create(erp_nr="1006", name="Bestehend")
        Price.objects.create(
            product=product,
            sales_channel=self.default_channel,
            price=Decimal("90.00"),
        )
        preserved_price = Price.objects.create(
            product=product,
            sales_channel=b2b_channel,
            price=Decimal("137.00"),
            rebate_quantity=20,
            rebate_price=Decimal("129.00"),
            special_price=Decimal("119.00"),
            special_start_date=timezone.now() - timedelta(days=1),
            special_end_date=timezone.now() + timedelta(days=1),
        )

        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1006", is_active=True)
        artikel_service.get_price.return_value = Decimal("100.00")
        artikel_service.get_rebate_quantity.return_value = 10
        artikel_service.get_rebate_price.return_value = Decimal("95.00")

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        default_price = Price.objects.get(product=product, sales_channel=self.default_channel)
        preserved_price.refresh_from_db()

        self.assertEqual(default_price.price, Decimal("100.00"))
        self.assertEqual(default_price.rebate_quantity, 10)
        self.assertEqual(default_price.rebate_price, Decimal("95.00"))
        self.assertEqual(preserved_price.price, Decimal("137.00"))
        self.assertEqual(preserved_price.rebate_quantity, 20)
        self.assertEqual(preserved_price.rebate_price, Decimal("129.00"))
        self.assertEqual(preserved_price.special_price, Decimal("119.00"))

    def test_sync_creates_missing_non_default_channel_prices_from_factor(self):
        b2b_channel = ShopwareSettings.objects.create(
            name="B2B",
            is_active=True,
            price_factor=Decimal("1.25"),
        )

        cmd = MicrotechSyncProductsCommand()
        artikel_service = self._build_artikel_service(erp_nr="1007", is_active=True)
        artikel_service.get_price.return_value = Decimal("100.00")
        artikel_service.get_rebate_quantity.return_value = 10
        artikel_service.get_rebate_price.return_value = Decimal("95.00")
        artikel_service.get_special_price.return_value = Decimal("80.00")
        artikel_service.get_special_start_date.return_value = timezone.now() - timedelta(days=1)
        artikel_service.get_special_end_date.return_value = timezone.now() + timedelta(days=1)

        cmd._sync_current_record(
            artikel_service,
            self._build_lager_service(),
            tax_map={
                Decimal("19.00"): self.tax_19,
                Decimal("7.00"): self.tax_7,
            },
            preserve_is_active=False,
        )

        derived_price = Price.objects.get(product__erp_nr="1007", sales_channel=b2b_channel)
        self.assertEqual(derived_price.price, Decimal("125.00"))
        self.assertEqual(derived_price.rebate_quantity, 10)
        self.assertEqual(derived_price.rebate_price, Decimal("118.75"))
        self.assertEqual(derived_price.special_price, Decimal("100.00"))

    def test_update_product_payload_writes_default_price_to_vk0_and_vk1(self):
        product = Product.objects.create(erp_nr="1008", name="Payload Artikel", tax=self.tax_19)
        Price.objects.create(
            product=product,
            sales_channel=self.default_channel,
            price=Decimal("10.25"),
            rebate_quantity=5,
            rebate_price=Decimal("9.25"),
            special_price=Decimal("8.25"),
            special_start_date=timezone.now(),
            special_end_date=timezone.now() + timedelta(days=7),
        )

        payload = MicrotechUpdateProductCommand()._build_input_data(product)

        self.assertNotIn("price", payload)
        self.assertNotIn("rebateQuantity", payload)
        self.assertNotIn("rebatePrice", payload)
        self.assertNotIn("specialPrice", payload)
        self.assertEqual(
            payload["priceTrees"],
            [
                {
                    "tree": "Vk0",
                    "price": "10,25",
                    "rebateQuantity": 5,
                    "rebatePrice": "9,25",
                    "specialPrice": "8,25",
                    "specialStartDate": payload["priceTrees"][0]["specialStartDate"],
                    "specialEndDate": payload["priceTrees"][0]["specialEndDate"],
                },
                {
                    "tree": "Vk1",
                    "price": "10,25",
                    "rebateQuantity": 5,
                    "rebatePrice": "9,25",
                    "specialPrice": "8,25",
                    "specialStartDate": payload["priceTrees"][0]["specialStartDate"],
                    "specialEndDate": payload["priceTrees"][0]["specialEndDate"],
                }
            ],
        )

    def test_update_prices_payload_writes_default_price_to_vk0_and_vk1(self):
        product = Product.objects.create(erp_nr="1009", name="Nur Preis")
        Price.objects.create(
            product=product,
            sales_channel=self.default_channel,
            price=Decimal("11.25"),
            rebate_quantity=10,
            rebate_price=Decimal("10.25"),
        )

        payload = MicrotechUpdatePricesCommand()._get_price_data(product)

        self.assertNotIn("price", payload)
        self.assertNotIn("rebateQuantity", payload)
        self.assertNotIn("rebatePrice", payload)
        self.assertEqual(
            payload["priceTrees"],
            [
                {
                    "tree": "Vk0",
                    "price": "11,25",
                    "rebateQuantity": 10,
                    "rebatePrice": "10,25",
                },
                {
                    "tree": "Vk1",
                    "price": "11,25",
                    "rebateQuantity": 10,
                    "rebatePrice": "10,25",
                }
            ],
        )


class MicrotechArtikelServiceTaxTest(TestCase):
    def test_get_tax_rate_uses_optional_field_and_falls_back_to_tax_key(self):
        service = MicrotechArtikelService.__new__(MicrotechArtikelService)
        service.get_field = MagicMock(return_value=None)
        service.get_tax_key = MagicMock(return_value="M19")

        rate = MicrotechArtikelService.get_tax_rate(service)

        self.assertEqual(rate, Decimal("19.00"))
        service.get_field.assert_called_once_with("StSchlSz", silent=True)

    def test_extracts_filename_from_windows_path_and_url(self):
        self.assertEqual(
            MicrotechDatasetService._find_image_filename_in_path(r"C:\Bilder\Unterordner\produkt-1.JPG"),
            "produkt-1.JPG",
        )
        self.assertEqual(
            MicrotechDatasetService._find_image_filename_in_path("https://cdn.example.com/img/produkt-2.png?size=large"),
            "produkt-2.png",
        )


class MicrotechPriceFactorGuardTest(TestCase):
    def test_normalize_price_factor_accepts_expected_value(self):
        factor, suspicious = MicrotechSyncProductsCommand._normalize_price_factor(Decimal("1.25"))
        self.assertEqual(factor, Decimal("1.25"))
        self.assertFalse(suspicious)

    def test_normalize_price_factor_rejects_factor_100(self):
        factor, suspicious = MicrotechSyncProductsCommand._normalize_price_factor(Decimal("100"))
        self.assertEqual(factor, Decimal("1.0"))
        self.assertTrue(suspicious)
