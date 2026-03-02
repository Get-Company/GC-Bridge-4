from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from products.admin import PriceActionForm, PriceAdmin, ProductAdmin
from products.models import Price, Product
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
