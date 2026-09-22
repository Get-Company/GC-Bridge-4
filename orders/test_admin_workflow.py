import json
from unittest.mock import MagicMock, patch

from django.contrib import admin as django_admin
from django.test import RequestFactory
from django.test import SimpleTestCase, TestCase

from core.admin import BaseAdmin
from customer.models import Address, Customer
from orders.admin import OrderAdmin, PayPalOrderAdmin
from orders.models import MicrotechOrderSyncWorkflow, Order, PayPalOrder
from orders.test_order_sync_workflow import make_order


class OrderAdminSearchTest(SimpleTestCase):
    def test_search_includes_customer_first_and_last_name(self):
        model_admin = OrderAdmin(Order, django_admin.site)

        self.assertIn("paypal_transaction_id", model_admin.search_fields)
        self.assertIn("customer__erp_nr", model_admin.search_fields)
        self.assertIn("customer__addresses__first_name", model_admin.search_fields)
        self.assertIn("customer__addresses__last_name", model_admin.search_fields)
        self.assertIn("customer__name", model_admin.search_fields)

    def test_customer_change_uses_a_native_unfold_dialog(self):
        model_admin = OrderAdmin(Order, django_admin.site)
        detail_action_dropdown = model_admin.actions_detail[0]

        self.assertEqual(detail_action_dropdown["title"], "Aktionen")
        self.assertEqual(detail_action_dropdown["icon"], "more_vert")
        self.assertIn("request_customer_change_detail", detail_action_dropdown["items"])
        self.assertNotIn("address_reconciliation_detail", detail_action_dropdown["items"])
        self.assertIn("customer_merge_row", model_admin.actions_row)
        self.assertNotIn("address_reconciliation_row", model_admin.actions_row)
        self.assertNotIn("resume_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertNotIn("abort_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertNotIn("restart_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertIn("customer", model_admin.readonly_fields)
        self.assertIsNotNone(model_admin.request_customer_change_detail.dialog)
        self.assertIsNotNone(model_admin.abort_microtech_sync_detail.dialog)
        self.assertIsNotNone(model_admin.restart_microtech_sync_detail.dialog)

    def test_customer_merge_row_action_opens_merge_with_order_adrnr(self):
        model_admin = OrderAdmin(Order, django_admin.site)
        order = Order(customer=Customer(erp_nr="100123"))
        request = RequestFactory().get("/")
        request.user = MagicMock()
        request.user.has_perm.return_value = True

        with patch.object(model_admin, "get_object", return_value=order):
            response = model_admin.customer_merge_row(request, "1")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/customer-merge/?customer_number=100123")


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


class OrderAdminStatusTransitionTest(SimpleTestCase):
    def setUp(self):
        self.model_admin = OrderAdmin(Order, django_admin.site)
        self.request_factory = RequestFactory()

    def _request(self, *, method: str, payload: dict | None = None):
        if method.upper() == "GET":
            request = self.request_factory.get("/", data=payload or {})
        else:
            request = self.request_factory.post(
                "/",
                data=json.dumps(payload or {}),
                content_type="application/json",
            )
        request.user = MagicMock()
        request.user.has_perm.return_value = True
        return request

    @patch.object(OrderAdmin, "_refresh_local_states")
    @patch("orders.admin.OrderService")
    def test_set_state_passes_complete_to_the_order_setter(self, order_service, refresh_states):
        order = Order(api_id="order-1", order_state="in_progress")
        request = self._request(method="POST", payload={"scope": "order", "action": "complete"})

        with patch.object(self.model_admin, "get_object", return_value=order):
            response = self.model_admin.shopware_set_state_view(request, "1")

        self.assertEqual(response.status_code, 200)
        order_service.return_value.set_order_state.assert_called_once_with(order_id="order-1", action_name="complete")
        refresh_states.assert_called_once_with(order=order, service=order_service.return_value)

    @patch.object(OrderAdmin, "_refresh_local_states")
    @patch("orders.admin.OrderService")
    def test_state_options_use_the_refreshed_entity_state_as_fallback(self, order_service, refresh_states):
        order = Order(api_id="order-1", order_state="in_progress")
        order_service.return_value.get_available_transition_actions.return_value = [{"action": "complete"}]
        request = self._request(method="GET", payload={"scope": "order"})

        with patch.object(self.model_admin, "get_object", return_value=order):
            response = self.model_admin.shopware_state_options_view(request, "1")

        payload = json.loads(response.content)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["current_state"], "in_progress")
        refresh_states.assert_called_once_with(order=order, service=order_service.return_value)


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

    @staticmethod
    def _set_customer_defaults(
        order: Order,
        address: Address | None = None,
        *additional: Address,
    ) -> Address:
        address = address or order.billing_address
        address.is_shipping = True
        address.is_invoice = True
        order.customer.order_connection_addresses = [address, *additional]
        return address

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
        self.assertIn("connection_status", self.model_admin.list_display)
        self.assertNotIn("payment_method", self.model_admin.list_display)
        self.assertNotIn("microtech_export_state", self.model_admin.list_display)
        self.assertNotIn("address_reconciliation_status", self.model_admin.list_display)
        self.assertNotIn("address_system_link_status", self.model_admin.list_display)
        self.assertEqual(self.model_admin.list_per_page, 20)

    def test_paypal_list_contains_customer_and_transaction_details(self):
        model_admin = PayPalOrderAdmin(PayPalOrder, django_admin.site)

        self.assertEqual(str(PayPalOrder._meta.verbose_name_plural), "PayPal")
        self.assertEqual(
            model_admin.list_display,
            (
                "order_number",
                "paypal_customer_details",
                "paypal_transaction_id",
                "payment_state",
                "purchase_date",
            ),
        )
        self.assertIn("paypal_transaction_id", model_admin.search_fields)
        self.assertIn("customer__erp_nr", model_admin.search_fields)

    def test_connection_column_stacks_both_link_badges(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        order.billing_address.api_id = "a" * 32
        order.billing_address.erp_ans_nr = 0
        order.billing_address.erp_asp_nr = 0
        self._set_customer_defaults(order)

        rendered = str(self.model_admin.connection_status(order))

        self.assertIn("Zugeordnet", rendered)
        self.assertIn("Eindeutig verknüpft", rendered)

    def test_paypal_customer_details_include_adrnr_and_address(self):
        order = self._order(country_code="DE", company="Muster GmbH")
        order.billing_address.street = "Musterstraße 1"
        order.billing_address.postal_code = "12345"
        order.billing_address.city = "Musterstadt"
        order.billing_address.phone = "+49 123 456"
        order.billing_address.email = "erika@example.com"
        model_admin = PayPalOrderAdmin(PayPalOrder, django_admin.site)

        rendered = str(model_admin.paypal_customer_details(order))

        self.assertIn("AdrNr: 100123", rendered)
        self.assertIn("Muster GmbH", rendered)
        self.assertIn("Musterstraße 1", rendered)
        self.assertIn("12345 Musterstadt", rendered)
        self.assertIn("erika@example.com", rendered)

    def test_address_reconciliation_status_marks_missing_microtech_ids(self):
        order = self._order(country_code="DE")
        self._set_customer_defaults(order)

        rendered = str(self.model_admin.address_reconciliation_status(order))

        self.assertIn("Abgleich nötig", rendered)
        self.assertIn("Anschrift offen", rendered)

    def test_address_reconciliation_status_marks_fully_matched_address(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        order.billing_address.erp_ans_nr = 1
        order.billing_address.erp_asp_nr = 1
        self._set_customer_defaults(order)

        rendered = str(self.model_admin.address_reconciliation_status(order))

        self.assertIn("Zugeordnet", rendered)

    def test_address_reconciliation_status_accepts_zero_as_a_microtech_mapping(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        order.billing_address.erp_ans_nr = 0
        order.billing_address.erp_asp_nr = 0
        self._set_customer_defaults(order)

        rendered = str(self.model_admin.address_reconciliation_status(order))

        self.assertIn("Zugeordnet", rendered)

    def test_system_link_status_requires_one_shopware_and_microtech_mapping(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        address = order.billing_address
        address.api_id = "a" * 32
        address.erp_ans_nr = 0
        address.erp_asp_nr = 0
        self._set_customer_defaults(order, address)

        rendered = str(self.model_admin.address_system_link_status(order))

        self.assertIn("Eindeutig verknüpft", rendered)

    def test_system_link_status_marks_duplicate_shopware_address_mapping(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        address = order.billing_address
        address.api_id = "a" * 32
        address.erp_ans_nr = 0
        address.erp_asp_nr = 0
        duplicate = Address(customer=order.customer, api_id=address.api_id, erp_ans_nr=1, erp_asp_nr=1)
        self._set_customer_defaults(order, address, duplicate)

        rendered = str(self.model_admin.address_system_link_status(order))

        self.assertIn("Verknüpfung offen", rendered)
        self.assertIn("SW6-ID nicht eindeutig", rendered)

    def test_address_statuses_use_customer_defaults_not_order_address_snapshots(self):
        order = self._order(country_code="DE")
        order.shipping_address = order.billing_address
        standard_address = Address(
            customer=order.customer,
            api_id="a" * 32,
            erp_ans_nr=1,
            erp_asp_nr=0,
            is_shipping=True,
            is_invoice=True,
        )
        order.customer.order_connection_addresses = [order.billing_address, standard_address]

        reconciliation = str(self.model_admin.address_reconciliation_status(order))
        system_link = str(self.model_admin.address_system_link_status(order))

        self.assertIn("Zugeordnet", reconciliation)
        self.assertIn("Eindeutig verknüpft", system_link)


class AdminTriggerTest(TestCase):
    def test_dialog_action_uses_hx_redirect_to_close_the_modal(self):
        model_admin = OrderAdmin(Order, django_admin.site)
        request = RequestFactory().post("/", HTTP_HX_REQUEST="true")

        response = model_admin._redirect_after_dialog(request, "71")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], "/admin/orders/order/71/change/")

    @patch("orders.admin.OrderSyncWorkflowService.start_or_resume_for_order")
    def test_run_upsert_uses_one_button_workflow_trigger(self, mock_trigger):
        order = make_order()
        admin = OrderAdmin(Order, django_admin.site)
        request = type("Request", (), {})()
        with patch.object(admin, "get_object", return_value=order), patch.object(admin, "message_user"):
            admin._run_microtech_upsert(request, str(order.pk))

        mock_trigger.assert_called_once_with(order)
