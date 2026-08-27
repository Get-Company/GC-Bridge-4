from __future__ import annotations

import logging
from threading import Event, Thread

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="microtech.submit_microtech_worker_operation")
def submit_microtech_worker_operation(job_id: int) -> None:
    from microtech.services import MicrotechJobSentinelService

    MicrotechJobSentinelService().submit_queued_microtech_worker_operation(job_id=job_id)


def _process_graphql_job_result(*, job_id: int, task_id: str) -> None:
    from microtech.services import MicrotechJobSentinelService
    import orders.tasks  # noqa: F401 - registers order sync continuations
    import products.tasks  # noqa: F401 - registers product sync continuations

    # A continuation can legitimately take minutes (for example a bounded
    # product-import batch).  Its lease is not a second execution trigger: it
    # is solely an observable worker-liveness signal.  Refresh it independently
    # of the handler so a long-running handler cannot look abandoned.
    stop_heartbeat = Event()

    def refresh_heartbeat() -> None:
        from django.db import close_old_connections

        try:
            while not stop_heartbeat.wait(60):
                close_old_connections()
                MicrotechJobSentinelService().heartbeat_continuation(job_id=job_id, task_id=task_id)
        except Exception:
            logger.exception("Continuation-Heartbeat für Microtech GraphQL Job %s fehlgeschlagen.", job_id)
        finally:
            close_old_connections()

    heartbeat_thread = Thread(
        target=refresh_heartbeat,
        name=f"microtech-continuation-heartbeat-{job_id}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        sentinel = MicrotechJobSentinelService()
        sentinel.heartbeat_continuation(job_id=job_id, task_id=task_id)
        sentinel.process_continuation(job_id=job_id, task_id=task_id)
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)


@shared_task(name="microtech.process_graphql_job_result", bind=True, soft_time_limit=30, time_limit=45)
def process_graphql_job_result(task, job_id: int) -> None:
    """Fallback runner for continuations without a dedicated work queue."""
    _process_graphql_job_result(job_id=job_id, task_id=str(task.request.id or ""))


@shared_task(name="orders.process_graphql_job_result", bind=True, soft_time_limit=240, time_limit=300)
def process_order_graphql_job_result(task, job_id: int) -> None:
    """Run a short, order-related GraphQL continuation on the orders queue."""
    _process_graphql_job_result(job_id=job_id, task_id=str(task.request.id or ""))


@shared_task(name="bulk.process_graphql_job_result", bind=True, soft_time_limit=7200, time_limit=7500)
def process_bulk_graphql_job_result(task, job_id: int) -> None:
    """Run a product/bulk continuation without occupying order or polling workers."""
    _process_graphql_job_result(job_id=job_id, task_id=str(task.request.id or ""))


@shared_task(name="microtech.poll_graphql_jobs")
def poll_graphql_jobs(limit: int = 50) -> int:
    from microtech.services import MicrotechJobSentinelService

    return MicrotechJobSentinelService().poll_due_jobs(limit=limit)


@shared_task(name="microtech.poll_graphql_job")
def poll_graphql_job(job_id: int) -> bool:
    from microtech.services import MicrotechJobSentinelService

    return MicrotechJobSentinelService().poll_job_once(job_id=job_id)


@shared_task(name="microtech.monitor_worker_health", soft_time_limit=30, time_limit=45)
def monitor_worker_health() -> dict:
    """Raise one actionable issue while the external COM worker is stopped.

    The GraphQL HTTP API can stay reachable although its worker no longer
    consumes jobs.  This independent check therefore covers precisely the
    outage mode that the generic HTTP health check cannot see.
    """
    from issues.services import create_task_issue
    from microtech.services import MicrotechGraphQLClientService
    from microtech.services.backup_mode import MicrotechBackupModeService

    if MicrotechBackupModeService.is_active():
        return {"status": "suppressed", "reason": "backup_mode"}

    try:
        result = MicrotechGraphQLClientService().microtech_worker_status()
        worker = dict(result.get("worker") or {})
    except Exception as exc:
        logger.exception("Microtech-Worker-Status konnte nicht abgefragt werden.")
        create_task_issue(
            title="[Microtech] Worker-Status nicht erreichbar",
            error_text=str(exc),
            description="Der GraphQL-Wrapper konnte den Zustand des Microtech-COM-Workers nicht liefern.",
        )
        return {"status": "error", "error": str(exc)}

    if not worker.get("running"):
        message = str(worker.get("connectionMessage") or "Microtech-COM-Worker läuft nicht.")
        logger.critical("Microtech-COM-Worker läuft nicht: %s", message)
        create_task_issue(
            title="[Microtech] COM-Worker läuft nicht",
            error_text=message,
            description="Neue GraphQL-Jobs bleiben liegen, bis der Microtech-COM-Worker wieder läuft.",
        )
        return {"status": "stopped", "worker": worker}

    return {"status": "ok", "worker": worker}


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
