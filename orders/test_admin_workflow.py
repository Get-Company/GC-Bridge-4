from unittest.mock import patch

from django.contrib import admin as django_admin
from django.test import SimpleTestCase, TestCase

from orders.admin import OrderAdmin
from orders.models import Order
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
        self.assertIn("abort_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertIn("restart_microtech_sync_detail", detail_action_dropdown["items"])
        self.assertIn("customer", model_admin.readonly_fields)
        self.assertIsNotNone(model_admin.request_customer_change_detail.dialog)
        self.assertIsNotNone(model_admin.abort_microtech_sync_detail.dialog)
        self.assertIsNotNone(model_admin.restart_microtech_sync_detail.dialog)


class AdminTriggerTest(TestCase):
    @patch("orders.admin.OrderSyncWorkflowService.start_for_order")
    def test_run_upsert_starts_workflow(self, mock_start):
        order = make_order()
        admin = OrderAdmin(Order, django_admin.site)
        request = type("Request", (), {})()
        with patch.object(admin, "get_object", return_value=order), patch.object(admin, "message_user"):
            admin._run_microtech_upsert(request, str(order.pk))

        mock_start.assert_called_once_with(order)
