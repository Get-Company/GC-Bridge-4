from django.test import TestCase

from microtech.models import MicrotechJob
from microtech.services.queue_worker import MicrotechQueueWorker


class MicrotechQueueWorkerClaimingTest(TestCase):
    def setUp(self):
        self.worker = MicrotechQueueWorker.get()
        self.worker.stop()
        with self.worker._registry_lock:
            self.worker._turn_events.clear()
            self.worker._done_events.clear()

    def tearDown(self):
        self.worker.stop()
        with self.worker._registry_lock:
            self.worker._turn_events.clear()
            self.worker._done_events.clear()

    def test_claim_next_job_ignores_queued_jobs_without_local_caller(self):
        job = MicrotechJob.objects.create(
            status=MicrotechJob.Status.QUEUED,
            priority=100,
            label="test",
            correlation_id="corr-no-caller",
        )

        claimed = self.worker._claim_next_job()

        self.assertIsNone(claimed)
        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechJob.Status.QUEUED)

    def test_claim_next_job_only_claims_locally_registered_correlation(self):
        local_job = MicrotechJob.objects.create(
            status=MicrotechJob.Status.QUEUED,
            priority=100,
            label="local",
            correlation_id="corr-local",
        )
        foreign_job = MicrotechJob.objects.create(
            status=MicrotechJob.Status.QUEUED,
            priority=1,
            label="foreign",
            correlation_id="corr-foreign",
        )

        self.worker.register_turn("corr-local")
        claimed = self.worker._claim_next_job()

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, local_job.id)
        local_job.refresh_from_db()
        foreign_job.refresh_from_db()
        self.assertEqual(local_job.status, MicrotechJob.Status.RUNNING)
        self.assertEqual(foreign_job.status, MicrotechJob.Status.QUEUED)

