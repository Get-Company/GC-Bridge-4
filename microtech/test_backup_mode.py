"""Tests fuer das Wartungs-Gate und den Watchdog des microtech-Backup-Fensters."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from microtech.models import MicrotechGraphQLJob, MicrotechSettings
from microtech.services.backup_mode import MicrotechBackupModeService
from microtech.services.graphql_client import MicrotechBackupModeActive
from microtech.services.job_sentinel import MicrotechJobSentinelService
from microtech.tasks import backup_mode_watchdog


def _open_window(*, deadline_offset_minutes: int = 90) -> MicrotechSettings:
    now = timezone.now()
    config = MicrotechSettings.load()
    config.backup_mode_active = True
    config.backup_mode_entered_at = now
    config.backup_mode_deadline = now + timedelta(minutes=deadline_offset_minutes)
    config.backup_mode_started_by = "7"
    config.save()
    return config


class BackupModeGateTests(TestCase):
    def test_wrapper_job_is_rejected_while_window_is_open(self):
        _open_window()

        with self.assertRaises(MicrotechBackupModeActive) as caught:
            MicrotechJobSentinelService().submit_wrapper_job(
                kind=MicrotechGraphQLJob.Kind.PRODUCT_READ,
                operation="requestProducts",
                submit=lambda: ("external-1", 5.0),
                request_payload={},
                context={},
                continuation="",
                next_step="",
            )

        self.assertIn("Backup-Fenster", str(caught.exception))
        self.assertEqual(
            MicrotechGraphQLJob.objects.count(),
            0,
            "Ein abgewiesener Job darf keine Job-Row hinterlassen.",
        )

    def test_wrapper_job_passes_when_no_window_is_open(self):
        job = MicrotechJobSentinelService().submit_wrapper_job(
            kind=MicrotechGraphQLJob.Kind.PRODUCT_READ,
            operation="requestProducts",
            submit=lambda: ("external-1", 5.0),
            request_payload={},
            context={},
            continuation="",
            next_step="",
        )
        self.assertEqual(job.external_job_id, "external-1")

    def test_maintenance_operations_pass_the_gate(self):
        _open_window()

        with patch("microtech.tasks.submit_microtech_worker_operation.delay"):
            job = MicrotechJobSentinelService().enqueue_microtech_worker_operation(
                operation="leaveMicrotechBackupMode",
                context={"source": "test"},
            )

        self.assertEqual(job.operation, "leaveMicrotechBackupMode")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.QUEUED)

    def test_graphql_execute_is_gated(self):
        from microtech.services.graphql_client import MicrotechGraphQLClientService

        _open_window()
        client = MicrotechGraphQLClientService()

        with patch("microtech.services.graphql_client.requests.post") as post:
            with self.assertRaises(MicrotechBackupModeActive):
                client.execute("query { health }")

        post.assert_not_called()


class BackupModeFlagTests(TestCase):
    """Das lokale Flag darf dem Wrapper niemals vorauseilen."""

    def _queued_job(self, operation: str) -> MicrotechGraphQLJob:
        return MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.MAINTENANCE,
            operation=operation,
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload={"operation": operation},
            context={"requested_by": "7"},
            delete_after_completion=False,
        )

    def test_flag_is_set_only_after_wrapper_confirms(self):
        job = self._queued_job("enterMicrotechBackupMode")
        deadline = (timezone.now() + timedelta(minutes=45)).isoformat()

        with patch(
            "microtech.services.job_sentinel.MicrotechGraphQLClientService.enter_microtech_backup_mode",
            return_value={"success": True, "ready": True, "deadlineAt": deadline, "message": "ok"},
        ):
            MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job.pk)

        config = MicrotechSettings.load()
        self.assertTrue(config.backup_mode_active)
        self.assertIsNotNone(config.backup_mode_deadline)
        self.assertEqual(config.backup_mode_started_by, "7")

        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.SUCCEEDED)

    def test_flag_stays_clear_when_wrapper_fails(self):
        job = self._queued_job("enterMicrotechBackupMode")

        with patch(
            "microtech.services.job_sentinel.MicrotechGraphQLClientService.enter_microtech_backup_mode",
            side_effect=RuntimeError("Dienst laesst sich nicht stoppen"),
        ):
            with self.assertRaises(RuntimeError):
                MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job.pk)

        self.assertFalse(MicrotechSettings.load().backup_mode_active)
        job.refresh_from_db()
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)

    def test_flag_is_cleared_after_successful_leave(self):
        _open_window()
        job = self._queued_job("leaveMicrotechBackupMode")

        with patch(
            "microtech.services.job_sentinel.MicrotechGraphQLClientService.leave_microtech_backup_mode",
            return_value={"success": True, "message": "wieder verbunden"},
        ):
            MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job.pk)

        config = MicrotechSettings.load()
        self.assertFalse(config.backup_mode_active)
        self.assertIsNone(config.backup_mode_deadline)

    def test_flag_stays_set_when_leave_fails(self):
        _open_window()
        job = self._queued_job("leaveMicrotechBackupMode")

        with patch(
            "microtech.services.job_sentinel.MicrotechGraphQLClientService.leave_microtech_backup_mode",
            side_effect=RuntimeError("Dienst startet nicht"),
        ):
            with self.assertRaises(RuntimeError):
                MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job.pk)

        self.assertTrue(
            MicrotechSettings.load().backup_mode_active,
            "Ein fehlgeschlagener Wiederanlauf darf das Fenster nicht als geschlossen melden.",
        )


class BackupModeWatchdogTests(TestCase):
    def test_watchdog_does_nothing_before_the_deadline(self):
        _open_window(deadline_offset_minutes=30)

        with patch("microtech.tasks.submit_microtech_worker_operation.delay") as delay:
            self.assertFalse(backup_mode_watchdog())

        delay.assert_not_called()
        self.assertEqual(MicrotechGraphQLJob.objects.count(), 0)

    def test_watchdog_does_nothing_without_an_open_window(self):
        with patch("microtech.tasks.submit_microtech_worker_operation.delay") as delay:
            self.assertFalse(backup_mode_watchdog())

        delay.assert_not_called()

    def test_watchdog_closes_the_window_after_the_deadline(self):
        _open_window(deadline_offset_minutes=-1)

        with patch("microtech.tasks.submit_microtech_worker_operation.delay"):
            self.assertTrue(backup_mode_watchdog())

        job = MicrotechGraphQLJob.objects.get()
        self.assertEqual(job.operation, "leaveMicrotechBackupMode")
        self.assertEqual(job.context.get("source"), "backup_mode_watchdog")

    def test_watchdog_survives_a_concurrent_maintenance_job(self):
        _open_window(deadline_offset_minutes=-1)
        MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.MAINTENANCE,
            operation="leaveMicrotechBackupMode",
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload={},
            context={},
            delete_after_completion=False,
        )

        with patch("microtech.tasks.submit_microtech_worker_operation.delay"):
            self.assertFalse(backup_mode_watchdog())

    def test_rejection_message_names_the_window(self):
        _open_window()
        message = MicrotechBackupModeService.rejection_message()
        self.assertIn("Backup-Fenster aktiv seit", message)
        self.assertIn("frei ab", message)
