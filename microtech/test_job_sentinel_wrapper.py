from unittest.mock import patch

from django.test import TestCase

from microtech.models import MicrotechGraphQLJob
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
    def test_celery_submission_hands_worker_operation_to_graphql_sentinel(self, mock_client_cls):
        mock_client_cls.return_value.submit_start_microtech_worker.return_value = ("worker-job-1", 45.0)
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.MAINTENANCE,
            operation="startMicrotechWorker",
            status=MicrotechGraphQLJob.Status.QUEUED,
        )

        submitted = MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job.pk)

        self.assertIsNotNone(submitted)
        job.refresh_from_db()
        self.assertEqual(job.external_job_id, "worker-job-1")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.WAITING_WEBHOOK)
        mock_client_cls.return_value.submit_start_microtech_worker.assert_called_once_with()
