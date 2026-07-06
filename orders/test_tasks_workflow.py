from unittest.mock import patch

from django.test import SimpleTestCase

from microtech.services.job_sentinel import CONTINUATIONS
from orders.services.order_sync_workflow import CONTINUATION_NAME


class ContinuationRegistrationTest(SimpleTestCase):
    def test_continuation_is_registered_on_import(self):
        import orders.tasks  # noqa: F401

        self.assertIn(CONTINUATION_NAME, CONTINUATIONS)

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.reconcile_failures")
    def test_reconcile_task_delegates(self, mock_reconcile):
        mock_reconcile.return_value = 3
        import orders.tasks as task_module

        self.assertEqual(task_module.reconcile_order_sync_workflows.run(), 3)


class PollReconcileLoggingTest(SimpleTestCase):
    @patch("orders.tasks.reconcile_order_sync_workflows")
    @patch("microtech.services.MicrotechJobSentinelService.poll_due_jobs")
    def test_poll_logs_reconcile_errors_instead_of_swallowing(self, mock_poll, mock_task):
        mock_poll.return_value = 0
        mock_task.run.side_effect = RuntimeError("Reconcile kaputt")
        from microtech.tasks import poll_graphql_jobs

        with self.assertLogs("microtech.tasks", level="ERROR") as logs:
            result = poll_graphql_jobs.run()

        self.assertEqual(result, 0)
        self.assertTrue(any("Reconcile kaputt" in message for message in logs.output))
