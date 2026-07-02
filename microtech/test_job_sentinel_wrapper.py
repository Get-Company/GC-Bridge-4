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
