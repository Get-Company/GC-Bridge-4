from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase

from microtech.management.commands.microtech_sync_products import Command as MicrotechSyncProductsCommand
from microtech.services.artikel import MicrotechArtikelService
from products.models import Product, Tax
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


class MicrotechArtikelServiceTaxTest(TestCase):
    def test_get_tax_rate_uses_optional_field_and_falls_back_to_tax_key(self):
        service = MicrotechArtikelService.__new__(MicrotechArtikelService)
        service.get_field = MagicMock(return_value=None)
        service.get_tax_key = MagicMock(return_value="M19")

        rate = MicrotechArtikelService.get_tax_rate(service)

        self.assertEqual(rate, Decimal("19.00"))
        service.get_field.assert_called_once_with("StSchlSz", silent=True)


class MicrotechPriceFactorGuardTest(TestCase):
    def test_normalize_price_factor_accepts_expected_value(self):
        factor, suspicious = MicrotechSyncProductsCommand._normalize_price_factor(Decimal("1.25"))
        self.assertEqual(factor, Decimal("1.25"))
        self.assertFalse(suspicious)

    def test_normalize_price_factor_rejects_factor_100(self):
        factor, suspicious = MicrotechSyncProductsCommand._normalize_price_factor(Decimal("100"))
        self.assertEqual(factor, Decimal("1.0"))
        self.assertTrue(suspicious)
