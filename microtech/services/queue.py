from __future__ import annotations

from datetime import timedelta
import time
from typing import Any

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from core.services import BaseService, CommandRuntimeService
from microtech.models import MicrotechJob


class MicrotechQueueService(BaseService):
    model = MicrotechJob

    RETRY_DELAYS_MINUTES = (1, 5, 15)
    TERMINAL_STATUSES = {
        MicrotechJob.Status.SUCCEEDED,
        MicrotechJob.Status.FAILED,
        MicrotechJob.Status.CANCELLED,
    }

    def enqueue(
        self,
        *,
        job_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = 100,
        max_retries: int = 3,
        run_after=None,
        correlation_id: str = "",
        created_by_id: int | None = None,
    ) -> MicrotechJob:
        now = timezone.now()
        return MicrotechJob.objects.create(
            job_type=job_type,
            status=MicrotechJob.Status.QUEUED,
            payload=payload or {},
            priority=priority,
            max_retries=max_retries,
            run_after=run_after or now,
            correlation_id=str(correlation_id or "").strip(),
            created_by_id=created_by_id,
        )

    @transaction.atomic
    def claim_next_job(self, *, worker_id: str) -> MicrotechJob | None:
        now = timezone.now()
        job = (
            MicrotechJob.objects.select_for_update(skip_locked=True)
            .filter(status=MicrotechJob.Status.QUEUED, run_after__lte=now)
            .order_by("priority", "run_after", "created_at", "id")
            .first()
        )
        if not job:
            return None
        job.status = MicrotechJob.Status.RUNNING
        job.started_at = now
        job.finished_at = None
        job.worker_id = worker_id
        job.attempt += 1
        job.last_error = ""
        job.save(
            update_fields=[
                "status",
                "started_at",
                "finished_at",
                "worker_id",
                "attempt",
                "last_error",
                "updated_at",
            ]
        )
        return job

    def mark_succeeded(self, job: MicrotechJob, *, result: dict[str, Any] | None = None) -> MicrotechJob:
        job.status = MicrotechJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.result = result or {}
        job.last_error = ""
        job.save(update_fields=["status", "finished_at", "result", "last_error", "updated_at"])
        return job

    def mark_failed(self, job: MicrotechJob, *, error: str) -> MicrotechJob:
        now = timezone.now()
        retry_allowed = job.attempt <= job.max_retries
        if retry_allowed:
            retry_index = max(0, min(job.attempt - 1, len(self.RETRY_DELAYS_MINUTES) - 1))
            delay_minutes = self.RETRY_DELAYS_MINUTES[retry_index]
            job.status = MicrotechJob.Status.QUEUED
            job.run_after = now + timedelta(minutes=delay_minutes)
            job.last_error = error[:4000]
            job.finished_at = None
            job.save(update_fields=["status", "run_after", "last_error", "finished_at", "updated_at"])
            return job

        job.status = MicrotechJob.Status.FAILED
        job.finished_at = now
        job.last_error = error[:4000]
        job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])
        return job

    def get(self, job_id: int) -> MicrotechJob:
        return MicrotechJob.objects.get(pk=job_id)

    def wait_for_terminal(
        self,
        *,
        job_id: int,
        timeout_seconds: int | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> MicrotechJob:
        deadline = None if timeout_seconds is None else (time.monotonic() + max(0, int(timeout_seconds)))
        missing_worker_since = None
        while True:
            job = self.get(job_id)
            if job.status in self.TERMINAL_STATUSES:
                return job
            if not self._has_running_worker():
                if missing_worker_since is None:
                    missing_worker_since = time.monotonic()
                elif (time.monotonic() - missing_worker_since) >= 10:
                    raise TimeoutError("No running microtech_worker found to process queued jobs.")
            else:
                missing_worker_since = None
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out while waiting for MicrotechJob #{job_id}.")
            time.sleep(max(0.1, poll_interval_seconds))

    def summarize(self) -> dict[str, Any]:
        counts = {
            item["status"]: item["count"]
            for item in MicrotechJob.objects.values("status").annotate(count=Count("id"))
        }
        oldest_queued = (
            MicrotechJob.objects.filter(status=MicrotechJob.Status.QUEUED)
            .order_by("created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        running_job = (
            MicrotechJob.objects.filter(status=MicrotechJob.Status.RUNNING)
            .order_by("started_at", "id")
            .first()
        )
        return {
            "counts": counts,
            "oldest_queued_at": oldest_queued.isoformat() if oldest_queued else "",
            "running_job_id": running_job.id if running_job else None,
            "running_job_type": running_job.job_type if running_job else "",
        }

    def delete_jobs(
        self,
        *,
        job_ids: list[int],
        include_running: bool = False,
    ) -> dict[str, Any]:
        unique_ids = sorted({int(job_id) for job_id in (job_ids or []) if int(job_id) > 0})
        if not unique_ids:
            return {
                "requested_ids": [],
                "existing_ids": [],
                "deleted_ids": [],
                "protected_running_ids": [],
                "deleted_count": 0,
            }

        queryset = MicrotechJob.objects.filter(id__in=unique_ids)
        existing_ids = list(queryset.values_list("id", flat=True))
        protected_running_ids = []
        if not include_running:
            protected_running_ids = list(
                queryset.filter(status=MicrotechJob.Status.RUNNING).values_list("id", flat=True)
            )
            queryset = queryset.exclude(status=MicrotechJob.Status.RUNNING)

        deleted_ids = list(queryset.values_list("id", flat=True))
        queryset.delete()
        return {
            "requested_ids": unique_ids,
            "existing_ids": existing_ids,
            "deleted_ids": deleted_ids,
            "protected_running_ids": protected_running_ids,
            "deleted_count": len(deleted_ids),
        }

    @staticmethod
    def _has_running_worker() -> bool:
        entries = CommandRuntimeService().list_runs(include_stale=False, cleanup_stale=True)
        return any(entry.get("command_name") == "microtech_worker" for entry in entries)
