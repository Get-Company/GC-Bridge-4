from unittest.mock import patch

from django.test import TestCase

from microtech.models import MicrotechGraphQLJob
from microtech.services.graphql_client import GraphQLMicrotechError
from microtech.services.job_sentinel import MicrotechJobSentinelService


class SubmitWrapperJobTest(TestCase):
    def test_submit_wrapper_job_creates_waiting_job(self):
        sentinel = MicrotechJobSentinelService()
        job = sentinel.submit_wrapper_job(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="updateCustomer",
            submit=lambda: ("ext-1", 30.0),
            request_payload={"customerNumber": "100012"},
            context={"workflow_id": 7, "step": "write_customer"},
            continuation="microtech_order_sync_advance",
            next_step="Kunde schreiben.",
        )
        job.refresh_from_db()
        self.assertEqual(job.external_job_id, "ext-1")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.WAITING_WEBHOOK)
        self.assertEqual(job.continuation, "microtech_order_sync_advance")
        self.assertEqual(job.context["step"], "write_customer")
        self.assertIsNotNone(job.submitted_at)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.next_poll_at)

    def test_submit_wrapper_job_marks_failed_on_submit_error(self):
        sentinel = MicrotechJobSentinelService()

        def boom():
            raise RuntimeError("wrapper down")

        with self.assertRaises(RuntimeError):
            sentinel.submit_wrapper_job(
                kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
                operation="updateCustomer",
                submit=boom,
                request_payload={},
                context={"workflow_id": 7, "step": "write_customer"},
                continuation="microtech_order_sync_advance",
                next_step="Kunde schreiben.",
            )
        job = MicrotechGraphQLJob.objects.get(context__step="write_customer")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)
        self.assertIn("wrapper down", job.error_message)
        self.assertIsNotNone(job.completed_at)

    def test_submit_wrapper_job_rejects_missing_external_job_id(self):
        sentinel = MicrotechJobSentinelService()

        with self.assertRaises(GraphQLMicrotechError):
            sentinel.submit_wrapper_job(
                kind=MicrotechGraphQLJob.Kind.ORDER_UPSERT,
                operation="createVorgang",
                submit=lambda: ("", 30.0),
                request_payload={},
                context={"workflow_id": 18, "step": "write_vorgang"},
                continuation="microtech_order_sync_advance",
                next_step="Vorgang schreiben.",
            )

        job = MicrotechGraphQLJob.objects.get(context__workflow_id=18)
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)
        self.assertIn("keine externe Job-ID", job.error_message)


class WorkerMaintenanceSentinelTest(TestCase):
    @patch("microtech.tasks.submit_microtech_worker_operation.delay")
    def test_enqueue_worker_operation_only_queues_a_celery_task(self, mock_delay):
        job = MicrotechJobSentinelService().enqueue_microtech_worker_operation(
            operation="stopMicrotechWorker",
            context={"source": "test"},
        )

        self.assertEqual(job.kind, MicrotechGraphQLJob.Kind.MAINTENANCE)
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.QUEUED)
        self.assertEqual(job.operation, "stopMicrotechWorker")
        mock_delay.assert_called_once_with(job.pk)

    @patch("microtech.services.job_sentinel.MicrotechGraphQLClientService")
    def test_celery_submission_completes_the_worker_operation_synchronously(self, mock_client_cls):
        # Der Wrapper beantwortet Wartungsoperationen sofort; es gibt keinen
        # Webhook, auf den der Job warten koennte.
        mock_client_cls.return_value.start_microtech_worker.return_value = {
            "success": True,
            "message": "Worker gestartet.",
            "worker": {"running": True, "microtechConnected": True},
        }
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.MAINTENANCE,
            operation="startMicrotechWorker",
            status=MicrotechGraphQLJob.Status.QUEUED,
        )

        submitted = MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job.pk)

        self.assertIsNotNone(submitted)
        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.SUCCEEDED)
        self.assertEqual(job.next_step, "Worker gestartet.")
        self.assertIsNone(job.next_poll_at)
        self.assertTrue(job.result_payload["success"])
        mock_client_cls.return_value.start_microtech_worker.assert_called_once_with()
