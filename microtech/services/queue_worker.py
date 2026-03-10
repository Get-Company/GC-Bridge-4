from __future__ import annotations

import threading
import time

from django.utils import timezone
from loguru import logger


class MicrotechQueueWorker:
    """Singleton worker that schedules Microtech COM connection turns.

    The worker does NOT create COM connections itself — it only signals
    callers (via threading.Event) that it's their turn.  The caller
    creates the COM connection in its own thread (COM thread-affinity).
    """

    _instance: MicrotechQueueWorker | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # correlation_id → Event mappings for in-process coordination
        self._turn_events: dict[str, threading.Event] = {}
        self._done_events: dict[str, threading.Event] = {}
        self._registry_lock = threading.Lock()

    @classmethod
    def get(cls) -> MicrotechQueueWorker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # -- Public API for callers ------------------------------------

    def register_turn(self, correlation_id: str) -> threading.Event:
        """Register a caller and return an Event that will be set when it's their turn."""
        turn_event = threading.Event()
        done_event = threading.Event()
        with self._registry_lock:
            self._turn_events[correlation_id] = turn_event
            self._done_events[correlation_id] = done_event
        return turn_event

    def get_done_event(self, correlation_id: str) -> threading.Event | None:
        with self._registry_lock:
            return self._done_events.get(correlation_id)

    def release_turn(self, correlation_id: str) -> None:
        """Called by the caller when it's done with the COM connection."""
        with self._registry_lock:
            done_event = self._done_events.pop(correlation_id, None)
            self._turn_events.pop(correlation_id, None)
        if done_event:
            done_event.set()

    # -- Worker lifecycle ------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="microtech-queue-worker", daemon=True)
        self._thread.start()
        logger.info("Microtech queue worker started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("Microtech queue worker stopped.")

    # -- Main loop -------------------------------------------------

    def _run(self) -> None:
        self._startup_cleanup()
        while not self._stop_event.is_set():
            job = self._claim_next_job()
            if job is None:
                self._stop_event.wait(timeout=1.0)
                continue
            self._process_job(job)

    def _startup_cleanup(self) -> None:
        """Reset any running jobs back to queued (crash recovery)."""
        from microtech.models import MicrotechJob

        count = MicrotechJob.objects.filter(status=MicrotechJob.Status.RUNNING).update(
            status=MicrotechJob.Status.QUEUED, started_at=None
        )
        if count:
            logger.warning("Microtech queue worker: reset {} stale running jobs to queued.", count)

    def _claim_next_job(self):
        from microtech.models import MicrotechJob

        # Only claim jobs that have a caller waiting in this process.
        # The in-memory event registry is process-local, therefore claiming
        # arbitrary queued jobs from other processes would create false
        # "orphaned job" failures.
        with self._registry_lock:
            local_correlation_ids = list(self._turn_events.keys())

        if not local_correlation_ids:
            return None

        job = (
            MicrotechJob.objects.filter(
                status=MicrotechJob.Status.QUEUED,
                correlation_id__in=local_correlation_ids,
            )
            .order_by("priority", "created_at")
            .first()
        )
        if job is None:
            return None
        job.status = MicrotechJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at", "updated_at"])
        return job

    def _process_job(self, job) -> None:
        from microtech.models import MicrotechJob

        correlation_id = job.correlation_id

        with self._registry_lock:
            turn_event = self._turn_events.get(correlation_id)
            done_event = self._done_events.get(correlation_id)

        if turn_event is None:
            # No in-process caller waiting — the process may have died or
            # this is an orphaned job.  Mark as failed.
            logger.warning("No caller registered for job {} ({}). Marking as failed.", job.id, correlation_id)
            job.status = MicrotechJob.Status.FAILED
            job.last_error = "No caller registered (orphaned job)"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
            self._cleanup_events(correlation_id)
            return

        # Signal the caller that it's their turn
        logger.debug("Granting turn to job {} ({}).", job.id, correlation_id)
        turn_event.set()

        # Wait for the caller to finish (with timeout to avoid deadlocks)
        if done_event and not done_event.wait(timeout=300):
            logger.error("Job {} ({}) timed out waiting for caller to finish.", job.id, correlation_id)
            job.refresh_from_db()
            if job.status == MicrotechJob.Status.RUNNING:
                job.status = MicrotechJob.Status.FAILED
                job.last_error = "Timeout waiting for caller to finish (300s)"
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
            self._cleanup_events(correlation_id)
            return

        self._cleanup_events(correlation_id)
        # Small pause between jobs to avoid busy-looping
        time.sleep(0.1)

    def _cleanup_events(self, correlation_id: str) -> None:
        with self._registry_lock:
            self._turn_events.pop(correlation_id, None)
            self._done_events.pop(correlation_id, None)
