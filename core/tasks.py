from __future__ import annotations

from collections.abc import Sequence

from celery import shared_task

from core.services import DatabaseBackupService


@shared_task(name="core.create_database_backup")
def create_database_backup(
    backup_id: int | None = None,
    *,
    table_names: Sequence[str] | None = None,
    label: str = "",
) -> dict[str, int | str]:
    service = DatabaseBackupService()
    if backup_id is None:
        backup = service.create_backup_request(table_names=table_names, label=label)
        backup_id = backup.pk
    backup = service.run_backup(backup_id)
    return {
        "backup_id": backup.pk,
        "status": backup.status,
        "file_name": backup.file_name,
    }


@shared_task(name="core.restore_database_backup")
def restore_database_backup(backup_id: int) -> dict[str, int | str]:
    backup = DatabaseBackupService().run_restore(backup_id)
    return {
        "backup_id": backup.pk,
        "restore_status": backup.restore_status,
    }


@shared_task(name="core.cleanup_sync_event_log")
def cleanup_sync_event_log(max_age_days: int = 30) -> int:
    from datetime import timedelta

    from django.utils import timezone

    from core.models import SyncEventLog

    cutoff = timezone.now() - timedelta(days=max_age_days)
    deleted, _ = SyncEventLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted
