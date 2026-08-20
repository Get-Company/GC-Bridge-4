from unittest.mock import patch

from django.contrib import admin as django_admin
from django.test import RequestFactory
from django.test import SimpleTestCase, TestCase

from core.admin import BaseAdmin
from customer.models import Address, Customer
from orders.admin import OrderAdmin
from orders.models import MicrotechOrderSyncWorkflow, Order
from orders.test_order_sync_workflow import make_order


class OrderAdminSearchTest(SimpleTestCase):
    def test_search_includes_customer_first_and_last_name(self):
        model_admin = OrderAdmin(Order, django_admin.site)

        self.assertIn("customer__addresses__first_name", model_admin.search_fields)
        self.assertIn("customer__addresses__last_name", model_admin.search_fields)
        self.assertIn("customer__name", model_admin.search_fields)

    def test_customer_change_uses_a_native_unfold_dialog(self):
        model_admin = OrderAdmin(Order, django_admin.site)
        detail_action_dropdown = model_admin.actions_detail[0]

        self.assertEqual(detail_action_dropdown["title"], "Aktionen")
        self.assertEqual(detail_action_dropdown["icon"], "more_vert")
        self.assertIn("request_customer_change_detail", detail_action_dropdown["items"])
        self.assertIn("address_reconciliation_detail", detail_action_dropdown["items"])
        self.assertIn("address_reconciliation_row", model_admin.actions_row)
        self.assertIn("abort_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertIn("restart_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertIn("customer", model_admin.readonly_fields)
        self.assertIsNotNone(model_admin.request_customer_change_detail.dialog)
        self.assertIsNotNone(model_admin.abort_microtech_sync_detail.dialog)
        self.assertIsNotNone(model_admin.restart_microtech_sync_detail.dialog)


class OrderAdminDeleteTest(SimpleTestCase):
    def test_deleting_an_order_does_not_require_direct_workflow_delete_permission(self):
        model_admin = OrderAdmin(Order, django_admin.site)
        permission_requirements = {
            Order._meta.verbose_name,
            MicrotechOrderSyncWorkflow._meta.verbose_name,
        }

        with patch.object(
            BaseAdmin,
            "get_deleted_objects",
            return_value=([], {}, permission_requirements, []),
        ):
            _, _, perms_needed, _ = model_admin.get_deleted_objects([], RequestFactory().get("/"))

        self.assertEqual(perms_needed, {Order._meta.verbose_name})


class OrderAdminListDisplayTest(SimpleTestCase):
    def setUp(self):
        self.model_admin = OrderAdmin(Order, django_admin.site)

    def _order(self, *, country_code: str, company: str = "", customer_name: str = "Erika") -> Order:
        customer = Customer(erp_nr="100123", name=customer_name)
        billing_address = Address(
            customer=customer,
            name1=company or "Frau",
            name2="Erika Musterfrau",
            country_code=country_code,
        )
        return Order(api_id="admin-list-display", customer=customer, billing_address=billing_address)

    def test_customer_column_shows_address_number_company_and_domestic_marker(self):
        order = self._order(country_code="DE", company="Muster GmbH")

        rendered = str(self.model_admin.customer_display(order))

        self.assertIn("100123 | Muster GmbH", rendered)
        self.assertIn("Inland", rendered)

    def test_customer_column_marks_eu_and_non_eu_customers(self):
        eu_rendered = str(self.model_admin.customer_display(self._order(country_code="AT")))
        non_eu_rendered = str(self.model_admin.customer_display(self._order(country_code="CH")))

        self.assertIn("100123 | Erika Musterfrau", eu_rendered)
        self.assertIn("Ausland · EU", eu_rendered)
        self.assertIn("Ausland", non_eu_rendered)
        self.assertNotIn("Ausland · EU", non_eu_rendered)

    def test_country_column_shows_flag_and_country_code(self):
        rendered = str(self.model_admin.country_display(self._order(country_code="CH")))

        self.assertIn("🇨🇭 CH", rendered)

    def test_order_list_uses_native_pagination_with_twenty_results(self):
        self.assertIn("customer_display", self.model_admin.list_display)
        self.assertIn("country_display", self.model_admin.list_display)
        self.assertEqual(self.model_admin.list_per_page, 20)

    def test_address_reconciliation_status_marks_missing_microtech_ids(self):
        order = self._order(country_code="DE")

        rendered = str(self.model_admin.address_reconciliation_status(order))

        self.assertIn("Abgleich nötig", rendered)
        self.assertIn("Anschrift offen", rendered)

    def test_address_reconciliation_status_marks_fully_matched_address(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        order.billing_address.erp_ans_nr = 1
        order.billing_address.erp_asp_nr = 1

        rendered = str(self.model_admin.address_reconciliation_status(order))

        self.assertIn("Zugeordnet", rendered)


class AdminTriggerTest(TestCase):
    def test_dialog_action_uses_hx_redirect_to_close_the_modal(self):
        model_admin = OrderAdmin(Order, django_admin.site)
        request = RequestFactory().post("/", HTTP_HX_REQUEST="true")

        response = model_admin._redirect_after_dialog(request, "71")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], "/admin/orders/order/71/change/")

    @patch("orders.admin.OrderSyncWorkflowService.start_for_order")
    def test_run_upsert_starts_workflow(self, mock_start):
        order = make_order()
        admin = OrderAdmin(Order, django_admin.site)
        request = type("Request", (), {})()
        with patch.object(admin, "get_object", return_value=order), patch.object(admin, "message_user"):
            admin._run_microtech_upsert(request, str(order.pk))

        mock_start.assert_called_once_with(order)
