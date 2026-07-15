from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from microtech.models import MicrotechGraphQLJob
from microtech.services.graphql_client import GraphQLMicrotechError
from microtech.services.job_sentinel import CONTINUATIONS, MicrotechJobSentinelService, register_continuation


def _make_job(**overrides) -> MicrotechGraphQLJob:
    defaults = dict(
        kind=MicrotechGraphQLJob.Kind.DATASET_RECORDS,
        operation="requestDatasetRecords",
        status=MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
        external_job_id=f"ext-{uuid.uuid4()}",
        attempt=0,
        max_attempts=3,
    )
    defaults.update(overrides)
    return MicrotechGraphQLJob.objects.create(**defaults)


class TestJobSentinelSubmission(TestCase):
    @patch("microtech.services.job_sentinel.MicrotechGraphQLClientService")
    def test_submit_product_update_tracks_remote_job(self, mock_client_cls):
        mock_client_cls.return_value.submit_update_product.return_value = ("remote-123", 45)

        job = MicrotechJobSentinelService().submit_product_update(
            erp_number="A-1000",
            input_data={"description": "Neu."},
            context={"source": "test"},
            next_step="Produkt schreiben.",
        )

        mock_client_cls.return_value.submit_update_product.assert_called_once_with(
            "A-1000",
            {"description": "Neu."},
        )
        self.assertEqual(job.kind, MicrotechGraphQLJob.Kind.PRODUCT_UPDATE)
        self.assertEqual(job.operation, "updateProduct")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.WAITING_WEBHOOK)
        self.assertEqual(job.external_job_id, "remote-123")
        self.assertEqual(job.request_payload, {"erpNumber": "A-1000", "input": {"description": "Neu."}})
        self.assertEqual(job.context, {"source": "test"})
        self.assertIsNotNone(job.next_poll_at)


@patch("microtech.services.job_sentinel.MicrotechGraphQLClientService")
class TestJobSentinelLoopSafety(TestCase):
    """Punkt 2 - der Poller darf niemals endlos laufen."""

    @patch.object(MicrotechJobSentinelService, "_fetch_remote_job", return_value={"status": "RUNNING"})
    def test_marks_failed_when_max_attempts_reached_and_still_running(self, _fetch, _client):
        job = _make_job(attempt=2, max_attempts=3)  # attempt wird auf 3 erhoeht

        result = MicrotechJobSentinelService().poll_job_once(job_id=job.pk)

        job.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)
        self.assertIsNone(job.next_poll_at)
        self.assertTrue(job.error_message)
        self.assertIsNotNone(job.completed_at)

    @patch.object(MicrotechJobSentinelService, "_fetch_remote_job", return_value={"status": "RUNNING"})
    def test_reschedules_when_under_max_attempts(self, _fetch, _client):
        job = _make_job(attempt=0, max_attempts=3)

        MicrotechJobSentinelService().poll_job_once(job_id=job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.RUNNING)
        self.assertIsNotNone(job.next_poll_at)
        self.assertGreater(job.next_poll_at, timezone.now())

    @patch.object(
        MicrotechJobSentinelService,
        "_fetch_remote_job",
        return_value={"status": "RUNNING", "retryAfterSeconds": 120},
    )
    def test_reschedule_honors_retry_after_seconds(self, _fetch, _client):
        job = _make_job(attempt=0, max_attempts=5)
        before = timezone.now()

        MicrotechJobSentinelService().poll_job_once(job_id=job.pk)

        job.refresh_from_db()
        delta = (job.next_poll_at - before).total_seconds()
        self.assertGreaterEqual(delta, 120)
        self.assertLessEqual(delta, 120 + MicrotechJobSentinelService.POLL_JITTER_SECONDS + 5)

    @patch.object(MicrotechJobSentinelService, "_fetch_remote_job", side_effect=GraphQLMicrotechError("boom"))
    def test_poll_error_marks_failed_when_max_attempts_reached(self, _fetch, _client):
        job = _make_job(attempt=2, max_attempts=3)

        result = MicrotechJobSentinelService().poll_job_once(job_id=job.pk)

        job.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)
        self.assertIsNone(job.next_poll_at)
        self.assertIn("boom", job.error_message)

    @patch.object(MicrotechJobSentinelService, "_fetch_remote_job", side_effect=GraphQLMicrotechError("boom"))
    def test_poll_error_reschedules_when_under_max_attempts(self, _fetch, _client):
        job = _make_job(attempt=0, max_attempts=3)
        before = timezone.now()

        result = MicrotechJobSentinelService().poll_job_once(job_id=job.pk)

        job.refresh_from_db()
        self.assertFalse(result)
        self.assertIn(job.status, MicrotechJobSentinelService.LOCAL_ACTIVE)
        self.assertIsNotNone(job.next_poll_at)
        self.assertGreater(job.next_poll_at, before)
        self.assertIn("boom", job.error_message)


class TestJobSentinelPoller(TestCase):
    """Punkt 4 - der Beat-Poller verteilt Arbeit und beansprucht Jobs."""

    @patch("microtech.tasks.poll_graphql_job.delay")
    def test_dispatches_one_task_per_due_job(self, mock_delay):
        past = timezone.now() - timedelta(minutes=1)
        j1 = _make_job(next_poll_at=past)
        j2 = _make_job(next_poll_at=None)

        count = MicrotechJobSentinelService().poll_due_jobs()

        self.assertEqual(count, 2)
        dispatched = {call.args[0] for call in mock_delay.call_args_list}
        self.assertEqual(dispatched, {j1.pk, j2.pk})

    @patch("microtech.tasks.poll_graphql_job.delay")
    def test_claims_dispatched_jobs_so_they_are_not_redispatched(self, mock_delay):
        past = timezone.now() - timedelta(minutes=1)
        job = _make_job(next_poll_at=past)
        service = MicrotechJobSentinelService()

        self.assertEqual(service.poll_due_jobs(), 1)
        job.refresh_from_db()
        self.assertGreater(job.next_poll_at, timezone.now())

        mock_delay.reset_mock()
        self.assertEqual(service.poll_due_jobs(), 0)
        mock_delay.assert_not_called()


class TestJobSentinelContinuations(TestCase):
    @patch(
        "microtech.tasks.process_graphql_job_result.delay",
        side_effect=ConnectionError("Celery broker nicht erreichbar"),
    )
    def test_dispatch_failure_keeps_successful_continuation_pending(self, _mock_delay):
        job = _make_job(
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            continuation="products.scheduled_product_sync_page",
            next_step="Continuation ausfuehren.",
            delete_after_completion=False,
        )

        MicrotechJobSentinelService()._dispatch_continuation(job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.SUCCEEDED)
        self.assertEqual(job.next_step, "Continuation ausfuehren.")
        self.assertIsNotNone(job.next_poll_at)
        self.assertLessEqual(job.next_poll_at, timezone.now())

    @patch.dict(CONTINUATIONS, {}, clear=True)
    def test_process_continuation_marks_job_failed_when_handler_raises(self):
        def failing_handler(_job):
            raise RuntimeError("Continuation kaputt")

        register_continuation("test.fail", failing_handler)
        job = _make_job(
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            continuation="test.fail",
            next_step="Continuation eingereiht.",
            delete_after_completion=False,
        )

        with self.assertRaises(RuntimeError):
            MicrotechJobSentinelService().process_continuation(job_id=job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)
        self.assertEqual(job.next_step, "Continuation fehlgeschlagen.")
        self.assertIn("Continuation kaputt", job.error_message)
        self.assertIsNone(job.next_poll_at)

    @patch("microtech.tasks.process_graphql_job_result.delay")
    @patch("microtech.tasks.poll_graphql_job.delay")
    def test_poll_due_jobs_dispatches_pending_continuations(self, mock_poll_delay, mock_continuation_delay):
        past = timezone.now() - timedelta(minutes=1)
        job = _make_job(
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            continuation="products.scheduled_product_sync_page",
            next_step="Continuation ausfuehren.",
            next_poll_at=past,
        )

        count = MicrotechJobSentinelService().poll_due_jobs()

        self.assertEqual(count, 1)
        mock_poll_delay.assert_not_called()
        mock_continuation_delay.assert_called_once_with(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.next_step, "Continuation eingereiht.")
        self.assertGreater(job.next_poll_at, timezone.now())
