from decimal import Decimal
from os import environ
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from products.models import MaboxExportSettings
from products.services.mabox_export import MaboxExportService
from products.services.mabox_mail import MaboxExportMailService


class _Collection:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Category:
    name = "Ordnung"
    level = 2
    sort_order = 100
    pk = 1

    def get_root(self):
        return SimpleNamespace(name="Deutschland")

    def get_category_path(self):
        return "Deutschland > Büro > Ordnung"


class _Price:
    is_special_active = False
    price = Decimal("70.30")
    rebate_quantity = 250
    rebate_price = Decimal("67.90")

    def get_current_price(self, *, as_float=False):
        return Decimal("70.30")


class MaboxExportServiceTests(SimpleTestCase):
    def setUp(self):
        self.product = SimpleNamespace(
            erp_nr="204116",
            gtin="04262545190042",
            name="Orgamappe",
            name_de="Orgamappe",
            description="Lang\r\nText",
            description_de="Lang\r\nText",
            description_short="Kurz\nText",
            description_short_de="Kurz\nText",
            factor=100,
            unit="Stck",
            min_purchase=50,
            purchase_unit=10,
            weight_net=Decimal("0.0300"),
            weight_gross=Decimal("0.0400"),
            tax=SimpleNamespace(rate=Decimal("19.00")),
            storage=SimpleNamespace(get_stock=Decimal("13407")),
            categories=_Collection([_Category()]),
            mabox_prices=[_Price()],
        )
        self.product.get_images = lambda: [SimpleNamespace(url="https://example.test/1.jpg")]
        self.product.mabox_packages = [
            SimpleNamespace(package_nr="204116-100", quantity=100, gtin=""),
            SimpleNamespace(package_nr="204116-250", quantity=250, gtin="04262545196310"),
        ]
        self.service = MaboxExportService(
            sales_channel=SimpleNamespace(name="Shopware DE"),
        )

    def test_mapping_has_exactly_50_columns_and_parent_child_rows(self):
        rows = list(self.service.iter_rows([self.product]))

        self.assertEqual(len(self.service.HEADERS), 50)
        self.assertEqual([len(row) for row in rows], [50, 50, 50])
        self.assertEqual(rows[0][0], "204116")
        self.assertEqual(rows[0][27], 1)
        self.assertEqual(rows[0][11:14], ["", "", ""])
        self.assertEqual(rows[1][3], "204116")
        self.assertEqual(rows[1][23], 100)
        self.assertEqual(rows[1][28:34], [1, 1, 1, 1, 1, 1])

    def test_package_price_uses_factor_and_tier_price(self):
        rows = list(self.service.iter_rows([self.product]))

        self.assertEqual(rows[1][12], "70,30")
        self.assertEqual(rows[2][12], "169,75")
        self.assertEqual(rows[2][11], "202,00")
        self.assertEqual(rows[2][13], "118,83")

    def test_package_stock_is_real_available_package_count(self):
        rows = list(self.service.iter_rows([self.product]))

        self.assertEqual(rows[0][16], 13407)
        self.assertEqual(rows[1][16], 134)
        self.assertEqual(rows[2][16], 53)
        self.assertEqual(rows[2][42], 53)

    def test_csv_uses_legacy_header_names(self):
        csv_content = self.service.render_csv([self.product])

        self.assertTrue(csv_content.startswith("Artikelnummer,GTIN,HAN,Vaterartikel,Artikelname"))
        self.assertIn('"169,75"', csv_content)


class MaboxExportMailServiceTests(SimpleTestCase):
    def test_recipient_list_accepts_common_separators(self):
        config = MaboxExportSettings(
            recipient_emails="one@example.com, two@example.com;\nthree@example.com"
        )

        self.assertEqual(
            config.recipients,
            ["one@example.com", "two@example.com", "three@example.com"],
        )

    def test_build_message_attaches_csv_and_marks_test_subject(self):
        config = MaboxExportSettings(
            recipient_emails="mabox@example.com",
            from_email="export@example.com",
            subject="Export {date}",
            message="Monat {month}",
        )
        service = MaboxExportMailService()
        now = timezone.now()

        with patch.dict(
            environ,
            {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
        ):
            message = service.build_message(
                config=config,
                csv_content="Artikelnummer\r\n204116\r\n",
                recipients=config.recipients,
                now=now,
                test_mode=True,
            )

        self.assertTrue(message.subject.startswith("[TEST] Export "))
        self.assertEqual(message.to, ["mabox@example.com"])
        self.assertEqual(message.from_email, "export@example.com")
        self.assertEqual(len(message.attachments), 1)
        self.assertTrue(message.attachments[0].filename.startswith("products_export_mabox_"))
        self.assertEqual(message.attachments[0].mimetype, "text/csv")
