from pathlib import Path
from datetime import timedelta
from decimal import Decimal
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from products.admin import ImageAdmin, PriceActionForm, PriceAdmin, ProductAdmin, ProductImageInline, ProductPropertyInline
from products.management.commands.import_legacy_product_properties import Command as ImportLegacyProductPropertiesCommand
from products.management.commands.scheduled_product_sync import Command as ScheduledProductSyncCommand
from products.models import Image, Price, Product, ProductImage, ProductProperty, PropertyGroup, PropertyValue
from shopware.models import ShopwareSettings


class PriceAdminActionTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.factory = RequestFactory()

    def test_percent_sign_in_action_description_does_not_crash(self):
        request = self.factory.get("/admin/products/price/")
        request.user = self.user

        admin_instance = PriceAdmin(Price, AdminSite())
        choices = dict(admin_instance.get_action_choices(request))

        self.assertEqual(choices["set_special_price_bulk"], "Sonderpreis setzen (%)")

    def test_action_form_contains_unfold_x_model_binding(self):
        form = PriceActionForm()
        self.assertEqual(form.fields["action"].widget.attrs.get("x-model"), "action")

    def test_set_special_price_bulk_updates_price(self):
        channel = ShopwareSettings.objects.create(name="Main", is_active=True, is_default=True)
        product = Product.objects.create(erp_nr="A-1000", name="Artikel A")
        price = Price.objects.create(product=product, sales_channel=channel, price=Decimal("100.00"))

        request = self.factory.post(
            "/admin/products/price/",
            data={
                "action": "set_special_price_bulk",
                "special_percentage": "10.00",
                "special_start_date": "2026-03-01T10:00",
                "special_end_date": "2026-03-31T10:00",
            },
        )
        request.user = self.user

        admin_instance = PriceAdmin(Price, AdminSite())
        admin_instance.message_user = lambda *args, **kwargs: None
        admin_instance.set_special_price_bulk(request, Price.objects.filter(pk=price.pk))

        price.refresh_from_db()
        self.assertEqual(price.special_percentage, Decimal("10.00"))
        self.assertEqual(price.special_price, Decimal("90.00"))
        self.assertTrue(timezone.is_aware(price.special_start_date))
        self.assertTrue(timezone.is_aware(price.special_end_date))


class ProductAdminSpecialPriceActionTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin2",
            email="admin2@example.com",
            password="pass",
        )
        self.factory = RequestFactory()
        self.channel = ShopwareSettings.objects.create(name="B2C", is_active=True, is_default=True)
        self.product = Product.objects.create(erp_nr="A-2000", name="Artikel B")
        self.price = Price.objects.create(
            product=self.product,
            sales_channel=self.channel,
            price=Decimal("120.00"),
        )

    def test_set_special_price_for_channel_updates_product_prices(self):
        request = self.factory.post(
            "/admin/products/product/",
            data={
                "action": "set_special_price_for_channel",
                "sales_channel": str(self.channel.pk),
                "special_percentage": "12.50",
                "special_start_date": "2026-03-01T08:00",
                "special_end_date": "2026-03-31T20:00",
            },
        )
        request.user = self.user

        admin_instance = ProductAdmin(Product, AdminSite())
        admin_instance.message_user = lambda *args, **kwargs: None
        admin_instance.set_special_price_for_channel(request, Product.objects.filter(pk=self.product.pk))

        self.price.refresh_from_db()
        self.assertEqual(self.price.special_percentage, Decimal("12.50"))
        self.assertEqual(self.price.special_price, Decimal("105.00"))
        self.assertTrue(timezone.is_aware(self.price.special_start_date))
        self.assertTrue(timezone.is_aware(self.price.special_end_date))

    def test_clear_special_price_for_channel_resets_product_prices(self):
        self.price.special_percentage = Decimal("12.50")
        self.price.save()

        request = self.factory.post(
            "/admin/products/product/",
            data={
                "action": "clear_special_price_for_channel",
                "sales_channel": str(self.channel.pk),
            },
        )
        request.user = self.user

        admin_instance = ProductAdmin(Product, AdminSite())
        admin_instance.message_user = lambda *args, **kwargs: None
        admin_instance.clear_special_price_for_channel(request, Product.objects.filter(pk=self.product.pk))

        self.price.refresh_from_db()
        self.assertIsNone(self.price.special_percentage)
        self.assertIsNone(self.price.special_price)
        self.assertIsNone(self.price.special_start_date)
        self.assertIsNone(self.price.special_end_date)

    @patch("products.admin.call_command", side_effect=RuntimeError("kaputt"))
    def test_sync_to_shopware_bulk_handles_command_error(self, mock_call_command):
        request = self.factory.post(
            "/admin/products/product/",
            data={
                "action": "sync_to_shopware",
            },
        )
        request.user = self.user

        admin_instance = ProductAdmin(Product, AdminSite())
        sent_messages = []
        admin_instance.message_user = lambda _request, message, level=messages.INFO: sent_messages.append(
            (message, level)
        )

        with patch.object(admin_instance, "_log_admin_error") as mock_log:
            admin_instance.sync_to_shopware(request, Product.objects.filter(pk=self.product.pk))

        mock_call_command.assert_called_once_with("shopware_sync_products", self.product.erp_nr)
        mock_log.assert_called_once()
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("1 Produkt(e) mit Fehlern: kaputt", sent_messages[0][0])
        self.assertEqual(sent_messages[0][1], messages.ERROR)

class ScheduledProductSyncCommandTest(TestCase):
    def setUp(self):
        self.channel = ShopwareSettings.objects.create(
            name="Default",
            is_active=True,
            is_default=True,
        )

    def test_clear_expired_specials_resets_only_expired_rows(self):
        now = timezone.now()
        product_a = Product.objects.create(erp_nr="A-3000", name="Artikel C")
        product_b = Product.objects.create(erp_nr="A-3001", name="Artikel D")

        expired = Price.objects.create(
            product=product_a,
            sales_channel=self.channel,
            price=Decimal("100.00"),
            special_percentage=Decimal("10.00"),
            special_start_date=now - timedelta(days=10),
            special_end_date=now - timedelta(days=1),
        )
        active = Price.objects.create(
            product=product_b,
            sales_channel=self.channel,
            price=Decimal("200.00"),
            special_percentage=Decimal("5.00"),
            special_start_date=now - timedelta(days=1),
            special_end_date=now + timedelta(days=1),
        )

        updated, product_ids = ScheduledProductSyncCommand._clear_expired_specials(now=now)

        self.assertEqual(updated, 1)
        self.assertSetEqual(product_ids, {product_a.id})
        expired.refresh_from_db()
        active.refresh_from_db()
        self.assertIsNone(expired.special_percentage)
        self.assertIsNone(expired.special_price)
        self.assertIsNone(expired.special_start_date)
        self.assertIsNone(expired.special_end_date)
        self.assertEqual(active.special_percentage, Decimal("5.00"))

    @patch("products.management.commands.scheduled_product_sync.call_command")
    def test_handle_runs_microtech_with_preserve_and_then_shopware(self, mock_call_command):
        cmd = ScheduledProductSyncCommand()
        with (
            patch.object(cmd, "_clear_expired_specials", return_value=(0, set())),
            patch.object(cmd, "_sync_expired_specials_to_microtech", return_value=(0, 0)) as mock_sync_microtech,
        ):
            cmd.handle(limit=50, exclude_inactive=False)

        mock_sync_microtech.assert_called_once_with(set(), write_base_price_back=False)
        self.assertEqual(mock_call_command.call_count, 2)
        mock_call_command.assert_has_calls(
            [
                call(
                    "microtech_sync_products",
                    all=True,
                    include_inactive=True,
                    preserve_is_active=True,
                    limit=50,
                ),
                call(
                    "shopware_sync_products",
                    all=True,
                    limit=50,
                ),
            ]
        )

    @patch("products.management.commands.scheduled_product_sync.call_command")
    def test_handle_passes_write_base_price_flag_when_enabled(self, mock_call_command):
        cmd = ScheduledProductSyncCommand()
        with (
            patch.object(cmd, "_clear_expired_specials", return_value=(0, set())),
            patch.object(cmd, "_sync_expired_specials_to_microtech", return_value=(0, 0)) as mock_sync_microtech,
        ):
            cmd.handle(limit=10, exclude_inactive=True, write_base_price_back=True)

        mock_sync_microtech.assert_called_once_with(set(), write_base_price_back=True)
        self.assertEqual(mock_call_command.call_count, 2)

    @patch("products.management.commands.scheduled_product_sync.logger")
    @patch("products.management.commands.scheduled_product_sync.call_command")
    def test_handle_uses_managed_scheduler_log_sink(self, mock_call_command, mock_logger):
        cmd = ScheduledProductSyncCommand()
        log_path = Path("/tmp/logs/weekly/scheduled_product_sync/scheduled_product_sync.2026-03-26.log")
        with (
            patch.object(cmd, "_add_file_sink", return_value=(99, log_path)),
            patch.object(cmd, "_clear_expired_specials", return_value=(0, set())),
            patch.object(cmd, "_sync_expired_specials_to_microtech", return_value=(0, 0)),
        ):
            cmd.handle(limit=5, exclude_inactive=False, write_base_price_back=False, log_file="")

        mock_logger.info.assert_any_call(
            "Scheduled product sync started. limit={} include_inactive={} write_base_price_back={} log_file={}",
            5,
            True,
            False,
            log_path,
        )
        mock_logger.info.assert_any_call("Scheduled product sync finished successfully. log_file={}", log_path)
        mock_logger.remove.assert_called_once_with(99)

    def test_is_suspicious_price_ratio_detects_factor_100(self):
        self.assertTrue(
            ScheduledProductSyncCommand._is_suspicious_price_ratio(
                django_price=Decimal("100.00"),
                microtech_price=Decimal("1.00"),
            )
        )

    def test_is_suspicious_price_ratio_ignores_small_delta(self):
        self.assertFalse(
            ScheduledProductSyncCommand._is_suspicious_price_ratio(
                django_price=Decimal("10.00"),
                microtech_price=Decimal("10.50"),
            )
        )


@override_settings(MICROTECH_IMAGE_BASE_URL="https://cdn.example.com/img/")
class ProductImageAdminAndSyncTest(TestCase):
    def test_product_admin_orders_by_status_then_erp_number(self):
        self.assertEqual(ProductAdmin.ordering, ("-is_active", "erp_nr"))

    def test_product_admin_uses_all_list_display_fields_as_links(self):
        self.assertEqual(ProductAdmin.list_display_links, ProductAdmin.list_display)

    def test_image_preview_uses_first_ordered_image(self):
        product = Product.objects.create(erp_nr="A-4000", name="Mit Bild")
        second = Image.objects.create(path="second.png")
        first = Image.objects.create(path="first.jpg")
        ProductImage.objects.create(product=product, image=second, order=2)
        ProductImage.objects.create(product=product, image=first, order=1)

        html = ProductAdmin(Product, AdminSite()).image_preview(product)

        self.assertIn("first.jpg", html)
        self.assertIn("cdn.example.com/img", html)
        self.assertIn('loading="lazy"', html)

    def test_get_ordered_product_images_includes_legacy_images_field_assignments(self):
        product = Product.objects.create(erp_nr="A-4003", name="Legacy Bilder")
        first = Image.objects.create(path="legacy-first.jpg")
        second = Image.objects.create(path="legacy-second.jpg")
        product.images.add(first, second)

        ordered = product.get_ordered_product_images()

        self.assertEqual([product_image.image.path for product_image in ordered], ["legacy-first.jpg", "legacy-second.jpg"])
        self.assertEqual([product_image.order for product_image in ordered], [1, 2])

    def test_get_ordered_product_images_merges_legacy_images_after_explicit_rows(self):
        product = Product.objects.create(erp_nr="A-4004", name="Gemischte Bilder")
        explicit = Image.objects.create(path="explicit.jpg")
        legacy = Image.objects.create(path="legacy.jpg")
        ProductImage.objects.create(product=product, image=explicit, order=3)
        product.images.add(explicit, legacy)

        ordered = product.get_ordered_product_images()

        self.assertEqual([product_image.image.path for product_image in ordered], ["explicit.jpg", "legacy.jpg"])
        self.assertEqual([product_image.order for product_image in ordered], [3, 4])

    def test_product_admin_uses_product_image_inline_and_hides_legacy_images_field(self):
        self.assertIn(ProductImageInline, ProductAdmin.inlines)
        self.assertEqual(ProductAdmin.exclude, ("images",))

    def test_product_admin_uses_product_property_inline(self):
        self.assertIn(ProductPropertyInline, ProductAdmin.inlines)

    def test_product_image_inline_renders_lazy_preview(self):
        product = Product.objects.create(erp_nr="A-4005", name="Inline Bild")
        image = Image.objects.create(path="inline.jpg")
        product_image = ProductImage.objects.create(product=product, image=image, order=1)

        html = ProductImageInline(Product, AdminSite()).image_preview(product_image)

        self.assertIn("inline.jpg", html)
        self.assertIn('loading="lazy"', html)

    def test_image_admin_renders_lazy_preview(self):
        image = Image.objects.create(path="admin-image.jpg")

        html = ImageAdmin(Image, AdminSite()).image_preview(image)

        self.assertIn("admin-image.jpg", html)
        self.assertIn('loading="lazy"', html)

    @patch("products.admin.call_command")
    def test_sync_products_bulk_delegates_to_shopware_command(self, mock_call_command):
        product = Product.objects.create(erp_nr="A-4001", sku="shopware-product-1", name="Mit Shopware Bild")

        success_count, error_count, error_messages = ProductAdmin(Product, AdminSite())._sync_products_bulk(
            Product.objects.filter(pk=product.pk)
        )

        self.assertEqual(success_count, 1)
        self.assertEqual(error_count, 0)
        self.assertEqual(error_messages, [])
        mock_call_command.assert_called_once_with("shopware_sync_products", "A-4001")

    @patch("products.admin.call_command", side_effect=RuntimeError("sync kaputt"))
    def test_sync_products_bulk_returns_error_when_command_fails(self, mock_call_command):
        product = Product.objects.create(erp_nr="A-4002", sku="shopware-product-2", name="Fehlerbild")

        success_count, error_count, error_messages = ProductAdmin(Product, AdminSite())._sync_products_bulk(
            [product]
        )

        self.assertEqual(success_count, 0)
        self.assertEqual(error_count, 1)
        self.assertEqual(error_messages, ["sync kaputt"])
        mock_call_command.assert_called_once_with("shopware_sync_products", "A-4002")


class LegacyProductPropertyImportCommandTest(TestCase):
    def setUp(self):
        self.product = Product.objects.create(erp_nr="581001", name="Quick-Tabs gelb")

    def test_imports_legacy_product_properties_from_sqlite(self):
        command = ImportLegacyProductPropertiesCommand()

        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(sqlite_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE products_product (
                        id INTEGER PRIMARY KEY,
                        erp_nr TEXT NOT NULL
                    );
                    CREATE TABLE products_propertygroup (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        name_de TEXT,
                        name_en TEXT
                    );
                    CREATE TABLE products_propertyvalue (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        name_de TEXT,
                        name_en TEXT,
                        group_id INTEGER NOT NULL
                    );
                    CREATE TABLE products_productproperty (
                        id INTEGER PRIMARY KEY,
                        product_id INTEGER NOT NULL,
                        value_id INTEGER NOT NULL
                    );
                    INSERT INTO products_product (id, erp_nr) VALUES (1, '581001');
                    INSERT INTO products_propertygroup (id, name, name_de, name_en) VALUES (9, 'Material', 'Material', 'Material');
                    INSERT INTO products_propertyvalue (id, name, name_de, name_en, group_id)
                    VALUES (112, 'Beschichteter Karton', 'Beschichteter Karton', 'Coated cardboard', 9);
                    INSERT INTO products_productproperty (id, product_id, value_id) VALUES (1001, 1, 112);
                    """
                )
                connection.commit()
            finally:
                connection.close()

            command.handle(
                sqlite_path=str(sqlite_path),
                dump_path="",
                rebuild_sqlite=False,
                erp_nrs=[],
                replace_product_properties=False,
            )

        group = PropertyGroup.objects.get(external_key="legacy-property-group:9")
        value = PropertyValue.objects.get(external_key="legacy-property-value:112")
        link = ProductProperty.objects.get(product=self.product, value=value)

        self.assertEqual(group.name_de, "Material")
        self.assertEqual(value.name_de, "Beschichteter Karton")
        self.assertEqual(value.group, group)
        self.assertEqual(link.external_key, "legacy-product-property:1001")

    def test_import_fills_missing_name_en_with_base_name_to_avoid_unique_conflicts(self):
        second_product = Product.objects.create(erp_nr="581002", name="Quick-Tabs rot")
        command = ImportLegacyProductPropertiesCommand()

        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(sqlite_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE products_product (
                        id INTEGER PRIMARY KEY,
                        erp_nr TEXT NOT NULL
                    );
                    CREATE TABLE products_propertygroup (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        name_de TEXT,
                        name_en TEXT
                    );
                    CREATE TABLE products_propertyvalue (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        name_de TEXT,
                        name_en TEXT,
                        group_id INTEGER NOT NULL
                    );
                    CREATE TABLE products_productproperty (
                        id INTEGER PRIMARY KEY,
                        product_id INTEGER NOT NULL,
                        value_id INTEGER NOT NULL
                    );
                    INSERT INTO products_product (id, erp_nr) VALUES (1, '581001');
                    INSERT INTO products_product (id, erp_nr) VALUES (2, '581002');
                    INSERT INTO products_propertygroup (id, name, name_de, name_en) VALUES (11, 'Farbe', 'Farbe', '');
                    INSERT INTO products_propertyvalue (id, name, name_de, name_en, group_id)
                    VALUES (201, 'Gelb', 'Gelb', '', 11);
                    INSERT INTO products_propertyvalue (id, name, name_de, name_en, group_id)
                    VALUES (202, 'Rot', 'Rot', '', 11);
                    INSERT INTO products_productproperty (id, product_id, value_id) VALUES (2001, 1, 201);
                    INSERT INTO products_productproperty (id, product_id, value_id) VALUES (2002, 2, 202);
                    """
                )
                connection.commit()
            finally:
                connection.close()

            command.handle(
                sqlite_path=str(sqlite_path),
                dump_path="",
                rebuild_sqlite=False,
                erp_nrs=[],
                replace_product_properties=False,
            )

        imported_values = list(
            PropertyValue.objects.filter(group__external_key="legacy-property-group:11").order_by("external_key")
        )

        self.assertEqual([value.name for value in imported_values], ["Gelb", "Rot"])
        self.assertEqual([value.name_en for value in imported_values], ["Gelb", "Rot"])
        self.assertTrue(ProductProperty.objects.filter(product=self.product, value=imported_values[0]).exists())
        self.assertTrue(ProductProperty.objects.filter(product=second_product, value=imported_values[1]).exists())

    def test_replace_product_properties_resets_existing_assignments_for_target_products(self):
        manual_group = PropertyGroup.objects.create(name="Manuell", name_de="Manuell")
        manual_value = PropertyValue.objects.create(group=manual_group, name="Alt", name_de="Alt")
        ProductProperty.objects.create(product=self.product, value=manual_value)
        command = ImportLegacyProductPropertiesCommand()

        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(sqlite_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE products_product (
                        id INTEGER PRIMARY KEY,
                        erp_nr TEXT NOT NULL
                    );
                    CREATE TABLE products_propertygroup (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        name_de TEXT,
                        name_en TEXT
                    );
                    CREATE TABLE products_propertyvalue (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        name_de TEXT,
                        name_en TEXT,
                        group_id INTEGER NOT NULL
                    );
                    CREATE TABLE products_productproperty (
                        id INTEGER PRIMARY KEY,
                        product_id INTEGER NOT NULL,
                        value_id INTEGER NOT NULL
                    );
                    INSERT INTO products_product (id, erp_nr) VALUES (1, '581001');
                    INSERT INTO products_propertygroup (id, name, name_de, name_en) VALUES (9, 'Material', 'Material', 'Material');
                    INSERT INTO products_propertyvalue (id, name, name_de, name_en, group_id)
                    VALUES (112, 'Beschichteter Karton', 'Beschichteter Karton', 'Coated cardboard', 9);
                    INSERT INTO products_productproperty (id, product_id, value_id) VALUES (1001, 1, 112);
                    """
                )
                connection.commit()
            finally:
                connection.close()

            command.handle(
                sqlite_path=str(sqlite_path),
                dump_path="",
                rebuild_sqlite=False,
                erp_nrs=["581001"],
                replace_product_properties=True,
            )

        self.assertFalse(ProductProperty.objects.filter(product=self.product, value=manual_value).exists())
        self.assertTrue(
            ProductProperty.objects.filter(
                product=self.product,
                value__external_key="legacy-property-value:112",
            ).exists()
        )

    def test_resolve_sqlite_path_raises_when_source_missing(self):
        command = ImportLegacyProductPropertiesCommand()

        with TemporaryDirectory() as temp_dir:
            missing_sqlite = Path(temp_dir) / "missing.sqlite3"

            with self.assertRaises(CommandError):
                command._resolve_sqlite_path(
                    sqlite_path_value=str(missing_sqlite),
                    dump_path_value="",
                    rebuild_sqlite=False,
                )
