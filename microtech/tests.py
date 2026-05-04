from datetime import timedelta
from decimal import Decimal
from unittest import skipIf
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from microtech.management.commands.microtech_sync_products import Command as MicrotechSyncProductsCommand
from microtech.models import MicrotechJob
from microtech.services.base import MicrotechDatasetService
from microtech.services.artikel import MicrotechArtikelService
try:
    from microtech.services.queue import MicrotechQueueService
except ModuleNotFoundError:  # pragma: no cover - legacy test import compatibility
    MicrotechQueueService = None
from products.models import Price, Product, ProductImage, Tax
from shopware.models import ShopwareSettings


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
        ShopwareSettings.objects.create(
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


@skipIf(MicrotechQueueService is None, "MicrotechQueueService is not available in this codebase.")
class MicrotechQueueServiceTest(TestCase):
    def test_enqueue_claim_and_mark_success(self):
        queue = MicrotechQueueService()
        job = queue.enqueue(
            job_type=MicrotechJob.JobType.LOOKUP_ARTICLE,
            payload={"artikel_nr": "204113"},
            priority=10,
        )

        claimed = queue.claim_next_job(worker_id="test-worker")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, job.id)
        self.assertEqual(claimed.status, MicrotechJob.Status.RUNNING)
        self.assertEqual(claimed.attempt, 1)

        queue.mark_succeeded(claimed, result={"found": True})
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, MicrotechJob.Status.SUCCEEDED)
        self.assertEqual(claimed.result.get("found"), True)

    def test_mark_failed_requeues_until_max_retries_then_fails(self):
        queue = MicrotechQueueService()
        job = queue.enqueue(
            job_type=MicrotechJob.JobType.SYNC_PRODUCTS,
            payload={"all": True},
            max_retries=1,
        )
        claimed = queue.claim_next_job(worker_id="worker-a")
        self.assertIsNotNone(claimed)
        queue.mark_failed(claimed, error="first error")
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, MicrotechJob.Status.QUEUED)

        claimed.run_after = timezone.now()
        claimed.save(update_fields=["run_after"])
        claimed = queue.claim_next_job(worker_id="worker-a")
        queue.mark_failed(claimed, error="second error")
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, MicrotechJob.Status.FAILED)

    def test_delete_jobs_skips_running_by_default(self):
        queue = MicrotechQueueService()
        first = queue.enqueue(job_type=MicrotechJob.JobType.SYNC_PRODUCTS)
        second = queue.enqueue(job_type=MicrotechJob.JobType.SYNC_CUSTOMER)

        running = queue.claim_next_job(worker_id="worker-a")
        self.assertIsNotNone(running)
        remaining_id = second.id if running.id == first.id else first.id

        result = queue.delete_jobs(job_ids=[first.id, second.id], include_running=False)

        self.assertIn(running.id, result["protected_running_ids"])
        self.assertIn(remaining_id, result["deleted_ids"])
        self.assertTrue(MicrotechJob.objects.filter(id=running.id).exists())
        self.assertFalse(MicrotechJob.objects.filter(id=remaining_id).exists())

    def test_delete_jobs_include_running_deletes_running_job(self):
        queue = MicrotechQueueService()
        job = queue.enqueue(job_type=MicrotechJob.JobType.SYNC_PRODUCTS)
        running = queue.claim_next_job(worker_id="worker-a")
        self.assertIsNotNone(running)

        result = queue.delete_jobs(job_ids=[job.id], include_running=True)

        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["protected_running_ids"], [])
        self.assertFalse(MicrotechJob.objects.filter(id=job.id).exists())
