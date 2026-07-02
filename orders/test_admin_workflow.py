from unittest.mock import patch

from django.contrib import admin as django_admin
from django.test import TestCase

from orders.admin import OrderAdmin
from orders.models import Order
from orders.test_order_sync_workflow import make_order


class AdminTriggerTest(TestCase):
    @patch("orders.admin.OrderSyncWorkflowService.start_for_order")
    def test_run_upsert_starts_workflow(self, mock_start):
        order = make_order()
        admin = OrderAdmin(Order, django_admin.site)
        request = type("Request", (), {})()
        with patch.object(admin, "get_object", return_value=order), patch.object(admin, "message_user"):
            admin._run_microtech_upsert(request, str(order.pk))

        mock_start.assert_called_once_with(order)
