from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core import live_events
from core.models import SyncEventLog


class SyncEventLogPersistenceTests(TestCase):
    def _emit(self, status):
        fake_redis = mock.MagicMock()
        with mock.patch.object(live_events, "_get_redis", return_value=fake_redis):
            live_events.emit_event(
                task="products.auto_sync",
                entity="4711",
                step="→ shopware6",
                status=status,
                summary="Preis konnte nicht gesetzt werden",
                run_id="run-1",
                target="shopware6",
                payload={"price": "abc"},
            )

    def test_error_event_is_persisted(self):
        self._emit("error")
        row = SyncEventLog.objects.get()
        self.assertEqual(row.task, "products.auto_sync")
        self.assertEqual(row.entity, "4711")
        self.assertEqual(row.status, "error")
        self.assertEqual(row.target, "shopware6")
        self.assertEqual(row.payload, {"price": "abc"})

    def test_skipped_event_is_persisted(self):
        self._emit("skipped")
        self.assertEqual(SyncEventLog.objects.filter(status="skipped").count(), 1)

    def test_ok_event_is_not_persisted(self):
        self._emit("ok")
        self.assertEqual(SyncEventLog.objects.count(), 0)


class CleanupTests(TestCase):
    def test_cleanup_removes_old_rows(self):
        from core.tasks import cleanup_sync_event_log

        old = SyncEventLog.objects.create(task="t", status="error", message="x")
        SyncEventLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        SyncEventLog.objects.create(task="t", status="error", message="fresh")

        deleted = cleanup_sync_event_log(max_age_days=30)
        self.assertEqual(deleted, 1)
        self.assertEqual(SyncEventLog.objects.count(), 1)
