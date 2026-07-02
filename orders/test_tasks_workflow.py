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
