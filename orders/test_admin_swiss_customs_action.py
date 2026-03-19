from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from customer.models import Address, Customer
from orders.models import Order, OrderDetail
from orders.services.swiss_customs_csv import SwissCustomsCsvExport


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
        self.request_factory = RequestFactory()

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

    @patch("orders.admin.SwissCustomsCsvExportService.export_order")
    @patch("orders.admin.OrderUpsertMicrotechService.refresh_erp_order_id")
    @patch("orders.admin.microtech_connection")
    def test_export_refreshes_erp_order_id_before_csv_generation(
        self,
        microtech_connection_mock,
        refresh_erp_order_id_mock,
        export_order_mock,
    ):
        microtech_connection_mock.return_value.__enter__.return_value = object()
        microtech_connection_mock.return_value.__exit__.return_value = False

        def _refresh(order, *, erp=None):
            order.erp_order_id = "BN-2000"
            order.save(update_fields=["erp_order_id", "updated_at"])
            return order.erp_order_id

        refresh_erp_order_id_mock.side_effect = _refresh
        export_order_mock.return_value = SwissCustomsCsvExport(
            filename="customs.csv",
            content="col\nvalue\n",
            row_count=1,
        )

        request = self.request_factory.get("/")
        request.user = self.admin_user
        model_admin = admin.site._registry[Order]

        response = model_admin._export_swiss_customs_csv(request, str(self.order.pk))

        self.assertEqual(response.status_code, 200)
        refresh_erp_order_id_mock.assert_called_once()
        export_order_mock.assert_called_once()
        exported_order = export_order_mock.call_args.args[0]
        self.assertEqual(exported_order.erp_order_id, "BN-2000")
        self.order.refresh_from_db()
        self.assertEqual(self.order.erp_order_id, "BN-2000")
