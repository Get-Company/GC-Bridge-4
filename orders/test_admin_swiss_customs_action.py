from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from customer.models import Address, Customer
from orders.models import Order, OrderDetail


class OrderAdminSwissCustomsActionTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret123",
        )
        self.client.force_login(self.admin_user)

        customer = Customer.objects.create(
            erp_nr="1000",
            email="kunde@example.com",
        )
        shipping = Address.objects.create(
            customer=customer,
            name1="ACME GmbH",
            name2="ACME GmbH",
            street="Musterstrasse 7a",
            postal_code="8000",
            city="Zuerich",
            country_code="CH",
            first_name="Max",
            last_name="Mustermann",
            is_shipping=True,
            is_invoice=True,
        )
        self.order = Order.objects.create(
            api_id="order-1",
            order_number="SW-10001",
            total_price=Decimal("23.00"),
            shipping_costs=Decimal("3.00"),
            customer=customer,
            billing_address=shipping,
            shipping_address=shipping,
        )
        OrderDetail.objects.create(
            order=self.order,
            erp_nr="ART-1",
            name="Exportartikel",
            unit="Stk",
            quantity=2,
            unit_price=Decimal("10.00"),
            total_price=Decimal("20.00"),
        )

    def test_order_changelist_renders_swiss_customs_row_action(self):
        response = self.client.get(reverse("admin:orders_order_changelist"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Zoll-CSV", content)

    def test_microtech_sidebar_contains_swiss_customs_mapping_link(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Schweiz Zoll Mapping", content)
