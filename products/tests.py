from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from products.admin import PriceActionForm, PriceAdmin, ProductAdmin
from products.management.commands.scheduled_product_sync import Command as ScheduledProductSyncCommand
from products.models import Image, Price, Product, ProductImage
from shopware.models import ShopwareSettings
from shopware.services.product_media import ProductMediaSyncService


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

    def test_sync_to_shopware_bulk_handles_service_initialization_error(self):
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

        with (
            patch("products.admin.ProductService", side_effect=RuntimeError("kaputt")),
            patch.object(admin_instance, "_log_admin_error") as mock_log,
        ):
            admin_instance.sync_to_shopware(request, Product.objects.filter(pk=self.product.pk))

        mock_log.assert_called_once()
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Sync fehlgeschlagen: kaputt", sent_messages[0][0])
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

    def test_sync_products_bulk_includes_media_payload_and_cover(self):
        product = Product.objects.create(
            erp_nr="A-4001",
            sku="shopware-product-1",
            name="Mit Shopware Bild",
        )
        first = Image.objects.create(path="cover.jpg")
        second = Image.objects.create(path="gallery.png")
        ProductImage.objects.create(product=product, image=first, order=1)
        ProductImage.objects.create(product=product, image=second, order=2)

        service = MagicMock()
        service.get_sku_map.return_value = {}

        success_count, error_count, _ = ProductAdmin(Product, AdminSite())._sync_products_bulk(
            Product.objects.filter(pk=product.pk),
            service,
        )

        self.assertEqual(success_count, 1)
        self.assertEqual(error_count, 0)
        service.bulk_upsert_media.assert_called_once()
        service.purge_product_media_by_product_ids.assert_called_once_with(product_ids=["shopware-product-1"])

        product_payload = service.bulk_upsert.call_args.args[0][0]
        self.assertEqual(product_payload["id"], "shopware-product-1")
        self.assertEqual(len(product_payload["media"]), 2)
        self.assertEqual(product_payload["coverId"], product_payload["media"][0]["id"])
        self.assertEqual([item["position"] for item in product_payload["media"]], [1, 2])
        product.refresh_from_db()
        self.assertTrue(product.shopware_image_sync_hash)

    def test_sync_products_bulk_skips_unchanged_media_uploads(self):
        product = Product.objects.create(
            erp_nr="A-4002",
            sku="shopware-product-2",
            name="Unveraendertes Bild",
        )
        image = Image.objects.create(path="cover-stable.jpg")
        ProductImage.objects.create(product=product, image=image, order=1)
        product.shopware_image_sync_hash = ProductMediaSyncService().build_media_sync_hash(product=product)
        product.save(update_fields=["shopware_image_sync_hash", "updated_at"])

        service = MagicMock()
        service.get_sku_map.return_value = {}

        success_count, error_count, _ = ProductAdmin(Product, AdminSite())._sync_products_bulk(
            Product.objects.filter(pk=product.pk),
            service,
        )

        self.assertEqual(success_count, 1)
        self.assertEqual(error_count, 0)
        service.purge_product_media_by_product_ids.assert_not_called()
        service.bulk_upsert_media.assert_not_called()

        product_payload = service.bulk_upsert.call_args.args[0][0]
        self.assertEqual(product_payload["id"], "shopware-product-2")
        self.assertNotIn("media", product_payload)
