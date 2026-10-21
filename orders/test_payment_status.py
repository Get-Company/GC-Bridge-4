from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from orders.services.payment_status import OrderPaymentStatusService


def local_order(**overrides):
    return {
        "pk": 1, "api_id": "order-1", "payment_state": "unconfirmed",
        "api_transaction_id": "old-payment", "paypal_id": "", "paypal_transaction_id": "",
        "payment_method": "PayPal", **overrides,
    }


def remote_order(*, primary="new-payment", state="paid"):
    return {
        "id": "order-1", "primaryOrderTransactionId": primary,
        "transactions": [
            {"id": "old-payment", "stateMachineState": {"technicalName": "failed"}},
            {"id": "new-payment", "stateMachineState": {"technicalName": state},
             "paymentMethod": {"name": "PayPal"},
             "customFields": {"swag_paypal_resource_id": "capture-1"}},
        ],
    }


class OrderPaymentStatusTest(SimpleTestCase):
    def setUp(self):
        self.service = OrderPaymentStatusService()
        self.rows = patch.object(self.service, "get_queryset").start()
        self.rows.return_value.exclude.return_value.order_by.return_value.values.return_value = [local_order()]
        self.api = patch("orders.services.payment_status.OrderService").start().return_value
        self.api.request_post.return_value = {"data": [remote_order()]}
        self.filtered = patch("orders.services.payment_status.Order.objects.filter").start()
        self.filtered.return_value.update.return_value = 1
        self.addCleanup(patch.stopall)

    def test_current_primary_payment_is_used_even_when_old_transaction_is_first(self):
        summary = self.service.sync()
        values = self.filtered.return_value.update.call_args.kwargs
        self.assertEqual(values["payment_state"], "paid")
        self.assertEqual(values["api_transaction_id"], "new-payment")
        self.assertEqual(values["paypal_id"], "capture-1")
        self.assertEqual(summary["orders_updated"], 1)
        self.assertLessEqual(set(values), {*self.service.payment_fields, "updated_at"})

    def test_request_has_no_order_state_filter_and_fetches_only_existing_ids(self):
        self.service.sync()
        endpoint, = self.api.request_post.call_args.args
        criteria = self.api.request_post.call_args.kwargs["payload"]
        self.assertEqual(endpoint, "/search/order")
        self.assertEqual(criteria["ids"], ["order-1"])
        self.assertNotIn("filter", criteria)
        self.assertNotIn("lineItems", criteria["associations"])

    def test_dry_run_reports_changes_without_database_writes(self):
        self.assertEqual(self.service.sync(dry_run=True)["orders_updated"], 1)
        self.filtered.assert_not_called()

    def test_already_matching_payment_does_not_write(self):
        self.api.request_post.return_value = {"data": [remote_order(primary="old-payment", state="failed")]}
        self.rows.return_value.exclude.return_value.order_by.return_value.values.return_value = [
            local_order(payment_state="failed"),
        ]
        self.assertEqual(self.service.sync()["orders_unchanged"], 1)
        self.filtered.assert_not_called()

    def test_missing_order_does_not_clear_payment_data(self):
        self.api.request_post.return_value = {"data": []}
        self.assertEqual(self.service.sync()["orders_missing"], 1)
        self.filtered.assert_not_called()

    def test_unavailable_primary_transaction_is_not_replaced_by_an_old_payment(self):
        self.api.request_post.return_value = {"data": [remote_order(primary="missing")]}
        self.assertEqual(self.service.sync()["orders_failed"], 1)
        self.filtered.assert_not_called()

    def test_failed_batch_does_not_prevent_remaining_batches(self):
        self.rows.return_value.exclude.return_value.order_by.return_value.values.return_value = [
            local_order(pk=1, api_id="order-2"), local_order(pk=2),
        ]
        self.api.request_post.side_effect = [RuntimeError("API unavailable"), {"data": [remote_order()]}]
        summary = self.service.sync(batch_size=1)
        self.assertEqual(summary["orders_failed"], 1)
        self.assertEqual(summary["orders_updated"], 1)
        self.assertEqual(summary["orders_seen"], 2)

    def test_concurrent_local_changes_are_protected_by_conditional_update(self):
        self.filtered.return_value.update.return_value = 0
        summary = self.service.sync()
        self.assertEqual(self.filtered.call_args.kwargs["payment_state"], "unconfirmed")
        self.assertEqual(self.filtered.call_args.kwargs["api_transaction_id"], "old-payment")
        self.assertEqual(summary["orders_updated"], 0)

    def test_json_api_attributes_and_data_wrappers_are_normalized(self):
        row = remote_order()
        row["transactions"] = {"data": [
            {"id": p["id"], "attributes": {k: v for k, v in p.items() if k != "id"}}
            for p in row["transactions"]
        ]}
        self.api.request_post.return_value = {"data": [{"id": row.pop("id"), "attributes": row}]}
        self.assertEqual(self.service.sync()["orders_updated"], 1)

    def test_older_shopware_falls_back_to_tracked_transaction(self):
        self.api.request_post.return_value = {"data": [remote_order(primary="")]}
        self.service.sync()
        self.assertEqual(self.filtered.return_value.update.call_args.kwargs["payment_state"], "failed")

    def test_refunds_are_refreshed_too(self):
        self.api.request_post.return_value = {"data": [remote_order(state="refunded_partially")]}
        self.service.sync()
        self.assertEqual(self.filtered.return_value.update.call_args.kwargs["payment_state"], "refunded_partially")

    def test_invalid_batch_size_is_rejected(self):
        for size in [0, -1, 101]:
            with self.assertRaises(ValueError):
                self.service.sync(batch_size=size)
        self.api.request_post.assert_not_called()


class PaymentStatusTaskTest(SimpleTestCase):
    def setUp(self):
        self.lock = patch("redis.Redis.from_url").start().return_value.lock.return_value
        self.lock.acquire.return_value = True
        self.command = patch("orders.tasks.call_command").start()
        patch("orders.tasks.emit_run_started").start()
        self.finished = patch("orders.tasks.emit_run_finished").start()
        self.addCleanup(patch.stopall)

    def test_task_calls_command_and_releases_lock(self):
        from orders.tasks import shopware_sync_payment_states
        shopware_sync_payment_states.run()
        self.command.assert_called_once_with("shopware_sync_payment_states")
        self.lock.release.assert_called_once()

    def test_overlap_is_skipped(self):
        from orders.tasks import shopware_sync_payment_states
        self.lock.acquire.return_value = False
        shopware_sync_payment_states.run()
        self.command.assert_not_called()
        self.lock.release.assert_not_called()

    def test_failure_remains_visible_and_releases_lock(self):
        from orders.tasks import shopware_sync_payment_states
        self.command.side_effect = RuntimeError("API unavailable")
        with self.assertRaises(RuntimeError):
            shopware_sync_payment_states.run()
        self.lock.release.assert_called_once()
        self.assertIn("Fehlgeschlagen", self.finished.call_args.args[2])


class PaymentStatusCommandTest(SimpleTestCase):
    @patch("orders.management.commands.shopware_sync_payment_states.OrderPaymentStatusService")
    def test_failed_sync_does_not_report_command_success(self, service):
        service.return_value.sync.return_value = {"orders_failed": 1}
        with self.assertRaises(CommandError):
            call_command("shopware_sync_payment_states", dry_run=True, stdout=StringIO())
        service.return_value.sync.assert_called_once_with(dry_run=True, batch_size=100)
