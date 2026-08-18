from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="microtech.submit_microtech_worker_operation")
def submit_microtech_worker_operation(job_id: int) -> None:
    from microtech.services import MicrotechJobSentinelService

    MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job_id)


@shared_task(name="microtech.process_graphql_job_result")
def process_graphql_job_result(job_id: int) -> None:
    from microtech.services import MicrotechJobSentinelService
    import orders.tasks  # noqa: F401 - registers order sync continuations
    import products.tasks  # noqa: F401 - registers product sync continuations

    MicrotechJobSentinelService().process_continuation(job_id=job_id)


@shared_task(name="microtech.poll_graphql_jobs")
def poll_graphql_jobs(limit: int = 50) -> int:
    from microtech.services import MicrotechJobSentinelService

    result = MicrotechJobSentinelService().poll_due_jobs(limit=limit)
    try:
        import orders.tasks

        orders.tasks.reconcile_order_sync_workflows.run()
    except Exception:
        # Reconcile darf den Poll nicht brechen, aber Fehler müssen sichtbar sein.
        logger.exception("Reconcile der Order-Sync-Workflows fehlgeschlagen.")
    return result


@shared_task(name="microtech.poll_graphql_job")
def poll_graphql_job(job_id: int) -> bool:
    from microtech.services import MicrotechJobSentinelService

    return MicrotechJobSentinelService().poll_job_once(job_id=job_id)


@shared_task(name="microtech.cleanup_old_graphql_jobs")
def cleanup_old_graphql_jobs(
    max_age_days: int = 30,
    limit: int = 100,
    terminal_only: bool = True,
) -> dict[str, int]:
    """Entfernt alte GraphQL-Jobs mit der vorhandenen Remote-Loeschmutation."""
    from microtech.services import MicrotechJobSentinelService

    return MicrotechJobSentinelService().cleanup_old_jobs(
        max_age_days=max_age_days,
        limit=limit,
        terminal_only=terminal_only,
    )


@shared_task(name="microtech.backup_mode_watchdog")
def backup_mode_watchdog() -> bool:
    """Schliesst ein Backup-Fenster, dessen Frist abgelaufen ist.

    Erste von zwei Ebenen: Ein vergessener oder haengengebliebener Backup-Lauf
    darf microtech nicht dauerhaft stilllegen. Die zweite Ebene ist der
    Scheduled Task GCMicrotech-BackupWatchdog auf dem Windows-Server, der auch
    dann greift, wenn GC-Bridge selbst nicht erreichbar ist.
    """
    from microtech.services import MicrotechJobSentinelService
    from microtech.services.backup_mode import MicrotechBackupModeService

    if not MicrotechBackupModeService.is_deadline_exceeded():
        return False

    config = MicrotechBackupModeService.load()
    logger.warning(
        "Frist des Microtech-Backup-Fensters ueberschritten (offen seit %s, Frist %s); "
        "microtech wird automatisch wieder hochgefahren.",
        config.backup_mode_entered_at,
        config.backup_mode_deadline,
    )

    try:
        MicrotechJobSentinelService().enqueue_microtech_worker_operation(
            operation="leaveMicrotechBackupMode",
            context={"source": "backup_mode_watchdog"},
        )
    except Exception:
        # Laeuft bereits eine Wartungsaktion, greift der naechste Lauf.
        logger.exception("Watchdog konnte das Schliessen des Backup-Fensters nicht einreihen.")
        return False

    return True
