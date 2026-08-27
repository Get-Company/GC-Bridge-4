from __future__ import annotations

import hmac
import json
import logging
import random
from uuid import uuid4
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from core.services import BaseService
from microtech.models import MicrotechGraphQLJob
from microtech.services.graphql_client import GraphQLMicrotechError, MicrotechGraphQLClientService

ContinuationHandler = Callable[[MicrotechGraphQLJob], None]

CONTINUATIONS: dict[str, ContinuationHandler] = {}
logger = logging.getLogger(__name__)


def register_continuation(name: str, handler: ContinuationHandler) -> None:
    cleaned = str(name or "").strip()
    if not cleaned:
        raise ValueError("Continuation name is required.")
    CONTINUATIONS[cleaned] = handler


class MicrotechJobSentinelService(BaseService):
    model = MicrotechGraphQLJob

    WORKER_OPERATIONS = frozenset(
        {
            "stopMicrotechWorker",
            "startMicrotechWorker",
            "enterMicrotechBackupMode",
            "leaveMicrotechBackupMode",
        }
    )

    REMOTE_SUCCESS = {"DONE", "SUCCEEDED", "SUCCESS"}
    REMOTE_FAILED = {"FAILED", "ERROR"}
    REMOTE_CANCELLED = {"CANCELLED", "CANCELED"}

    LOCAL_ACTIVE = {
        MicrotechGraphQLJob.Status.SUBMITTED,
        MicrotechGraphQLJob.Status.RUNNING,
        MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
    }
    TERMINAL_STATUSES = {
        MicrotechGraphQLJob.Status.SUCCEEDED,
        MicrotechGraphQLJob.Status.FAILED,
        MicrotechGraphQLJob.Status.CANCELLED,
        MicrotechGraphQLJob.Status.DELETE_FAILED,
    }

    # Fallback-Poll-Kadenz. retryAfterSeconds vom Wrapper hat Vorrang.
    DEFAULT_POLL_INTERVAL_SECONDS = 60
    MIN_POLL_INTERVAL_SECONDS = 10
    POLL_JITTER_SECONDS = 15
    POLL_ERROR_BACKOFF_SECONDS = 300
    # A remote-job poll is short-lived, so a two-minute dispatch backoff is
    # sufficient. Continuations use their own durable lifecycle below.
    POLL_DISPATCH_BACKOFF_SECONDS = 120
    CONTINUATION_LEASE_SECONDS = 300
    BULK_CONTINUATION_LEASE_SECONDS = 7_500
    CONTINUATION_LOCK_NAMESPACE = 82_641
    CONTINUATION_QUEUE_BY_NAME = {
        "microtech_order_sync_advance": "orders",
        "order_customer_change_apply": "orders",
        "products.scheduled_product_sync_page": "bulk",
    }

    def submit_dataset_records(
        self,
        *,
        input_data: dict[str, Any],
        continuation: str = "",
        context: dict[str, Any] | None = None,
        next_step: str = "",
        delete_after_completion: bool = True,
    ) -> MicrotechGraphQLJob:
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.DATASET_RECORDS,
            operation="requestDatasetRecords",
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload=input_data,
            context=context or {},
            continuation=str(continuation or "").strip(),
            next_step=next_step or "Warte auf Microtech GraphQL Webhook.",
            # Keep completed continuation rows for recovery and observability;
            # scheduled cleanup removes their remote/local records later.
            delete_after_completion=delete_after_completion and not bool(str(continuation or "").strip()),
        )
        client = MicrotechGraphQLClientService()
        try:
            external_job_id, retry_after = client.submit_dataset_job(input_data)
        except Exception as exc:
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise

        now = timezone.now()
        job.external_job_id = external_job_id
        job.status = MicrotechGraphQLJob.Status.WAITING_WEBHOOK
        job.submitted_at = now
        job.started_at = now
        job.next_poll_at = now + timedelta(seconds=max(int(retry_after), 30))
        job.save(
            update_fields=(
                "external_job_id",
                "status",
                "submitted_at",
                "started_at",
                "next_poll_at",
                "updated_at",
            )
        )
        return job

    def submit_product_update(
        self,
        *,
        erp_number: str,
        input_data: dict[str, Any],
        continuation: str = "",
        context: dict[str, Any] | None = None,
        next_step: str = "",
        delete_after_completion: bool = True,
    ) -> MicrotechGraphQLJob:
        erp_number = str(erp_number or "").strip()
        if not erp_number:
            raise ValueError("erp_number is required.")

        request_payload = {
            "erpNumber": erp_number,
            "input": input_data,
        }
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.PRODUCT_UPDATE,
            operation="updateProduct",
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload=request_payload,
            context=context or {},
            continuation=str(continuation or "").strip(),
            next_step=next_step or "Warte auf Microtech GraphQL Produkt-Update.",
            delete_after_completion=delete_after_completion and not bool(str(continuation or "").strip()),
        )
        client = MicrotechGraphQLClientService()
        try:
            external_job_id, retry_after = client.submit_update_product(erp_number, input_data)
        except Exception as exc:
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise

        now = timezone.now()
        job.external_job_id = external_job_id
        job.status = MicrotechGraphQLJob.Status.WAITING_WEBHOOK
        job.submitted_at = now
        job.started_at = now
        job.next_poll_at = now + timedelta(seconds=max(int(retry_after), 30))
        job.save(
            update_fields=(
                "external_job_id",
                "status",
                "submitted_at",
                "started_at",
                "next_poll_at",
                "updated_at",
            )
        )
        return job

    def submit_product_batch_read(
        self,
        *,
        erp_numbers: Sequence[str] | None = None,
        include_images: bool = True,
        continuation: str = "",
        context: dict[str, Any] | None = None,
        next_step: str = "",
        delete_after_completion: bool = True,
    ) -> MicrotechGraphQLJob:
        cleaned = [str(erp_number).strip() for erp_number in (erp_numbers or []) if str(erp_number).strip()]
        request_payload: dict[str, Any] = {"includeImages": bool(include_images)}
        if cleaned:
            request_payload["erpNumbers"] = cleaned
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.PRODUCT_READ,
            operation="requestProducts",
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload=request_payload,
            context=context or {},
            continuation=str(continuation or "").strip(),
            next_step=next_step or "Warte auf Microtech GraphQL Produkt-Batch.",
            delete_after_completion=delete_after_completion and not bool(str(continuation or "").strip()),
        )
        client = MicrotechGraphQLClientService()
        try:
            external_job_id, retry_after = client.submit_request_products(
                erp_numbers=cleaned or None,
                include_images=bool(include_images),
            )
        except Exception as exc:
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise

        now = timezone.now()
        job.external_job_id = external_job_id
        job.status = MicrotechGraphQLJob.Status.WAITING_WEBHOOK
        job.submitted_at = now
        job.started_at = now
        job.next_poll_at = now + timedelta(seconds=max(int(retry_after), 30))
        job.save(
            update_fields=(
                "external_job_id",
                "status",
                "submitted_at",
                "started_at",
                "next_poll_at",
                "updated_at",
            )
        )
        return job

    def submit_wrapper_job(
        self,
        *,
        kind: str,
        operation: str,
        submit: Callable[[], tuple[str, float]],
        request_payload: dict[str, Any],
        context: dict[str, Any],
        continuation: str,
        next_step: str,
        delete_after_completion: bool = True,
    ) -> MicrotechGraphQLJob:
        """Generischer Sentinel-Submit für Continuation-Ketten.

        Legt eine Job-Row mit Status QUEUED an, ruft das übergebene ``submit``-
        Callable auf (das das externe Job-ID und retryAfterSeconds liefert) und
        setzt anschließend ``external_job_id``, ``WAITING_WEBHOOK`` und
        ``next_poll_at``. Bei einer Ausnahme wird der Job auf FAILED gesetzt
        und die Ausnahme weitergeleitet.
        """
        # Waehrend eines Backup-Fensters steht die Verbindung zu microtech still;
        # neue Arbeit wird hier abgewiesen, statt spaeter ins Leere zu laufen.
        from microtech.services.backup_mode import MicrotechBackupModeService

        MicrotechBackupModeService.ensure_available(operation=operation)

        job = MicrotechGraphQLJob.objects.create(
            kind=kind,
            operation=operation,
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload=request_payload,
            context=context or {},
            continuation=str(continuation or "").strip(),
            next_step=next_step or "Warte auf Microtech GraphQL Job.",
            delete_after_completion=delete_after_completion and not bool(str(continuation or "").strip()),
        )
        try:
            external_job_id, retry_after = submit()
        except Exception as exc:
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise

        external_job_id = str(external_job_id or "").strip()
        if not external_job_id:
            error_message = f"Microtech GraphQL {operation} hat keine externe Job-ID zurueckgegeben."
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.error_message = error_message
            job.completed_at = timezone.now()
            job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise GraphQLMicrotechError(error_message)

        now = timezone.now()
        job.external_job_id = external_job_id
        job.status = MicrotechGraphQLJob.Status.WAITING_WEBHOOK
        job.submitted_at = now
        job.started_at = now
        job.next_poll_at = now + timedelta(seconds=max(int(retry_after), 30))
        job.save(
            update_fields=(
                "external_job_id",
                "status",
                "submitted_at",
                "started_at",
                "next_poll_at",
                "updated_at",
            )
        )
        return job

    def enqueue_microtech_worker_operation(
        self,
        *,
        operation: str,
        context: dict[str, Any] | None = None,
        deadline_minutes: int | None = None,
    ) -> MicrotechGraphQLJob:
        """Create a local maintenance job and submit it from a Celery worker.

        The admin request only writes the local job and queues Celery work. The
        external GraphQL call is deliberately kept out of the request cycle so
        COM start/stop work can never cause an admin timeout.
        """
        operation = str(operation or "").strip()
        if operation not in self.WORKER_OPERATIONS:
            raise ValueError(f"Unsupported Microtech worker operation: {operation or '-'}")

        active_statuses = (MicrotechGraphQLJob.Status.QUEUED, *self.LOCAL_ACTIVE)
        with transaction.atomic():
            active_job = (
                MicrotechGraphQLJob.objects.select_for_update()
                .filter(
                    kind=MicrotechGraphQLJob.Kind.MAINTENANCE,
                    operation__in=self.WORKER_OPERATIONS,
                    status__in=active_statuses,
                )
                .order_by("created_at")
                .first()
            )
            if active_job is not None:
                raise GraphQLMicrotechError(
                    f"Worker-Aktion {active_job.operation} (Job {active_job.pk}) läuft bereits."
                )

            job = MicrotechGraphQLJob.objects.create(
                kind=MicrotechGraphQLJob.Kind.MAINTENANCE,
                operation=operation,
                status=MicrotechGraphQLJob.Status.QUEUED,
                request_payload={"operation": operation, "deadlineMinutes": deadline_minutes},
                context=context or {},
                next_step="Warte auf die asynchrone GraphQL-Übergabe.",
                delete_after_completion=False,
            )

        try:
            from microtech.tasks import submit_microtech_worker_operation

            submit_microtech_worker_operation.delay(job.pk)
        except Exception as exc:
            MicrotechGraphQLJob.objects.filter(pk=job.pk).update(
                status=MicrotechGraphQLJob.Status.FAILED,
                error_message=str(exc),
                next_step="Celery-Task konnte nicht eingereiht werden.",
                completed_at=timezone.now(),
                updated_at=timezone.now(),
            )
            raise
        return job

    def submit_queued_microtech_worker_operation(self, *, job_id: int) -> MicrotechGraphQLJob | None:
        """Hand the queued worker operation to GraphQL and start Sentinel polling."""
        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().filter(pk=job_id).first()
            if job is None or job.kind != MicrotechGraphQLJob.Kind.MAINTENANCE:
                return None
            if job.operation not in self.WORKER_OPERATIONS or job.status != MicrotechGraphQLJob.Status.QUEUED:
                return job
            now = timezone.now()
            job.status = MicrotechGraphQLJob.Status.SUBMITTED
            job.submitted_at = now
            job.started_at = now
            job.next_step = "Warte auf die asynchrone GraphQL-Job-ID."
            job.save(update_fields=("status", "submitted_at", "started_at", "next_step", "updated_at"))

        # Wartungsoperationen laufen im API-Prozess des Wrappers, nicht im
        # COM-Worker - ein vom Worker abgearbeiteter Job koennte sich nicht
        # selbst stoppen. Der Aufruf ist deshalb synchron und liefert das
        # Endergebnis sofort; es gibt keinen Webhook, auf den man warten koennte.
        from microtech.services.backup_mode import MicrotechBackupModeService

        client = MicrotechGraphQLClientService()
        try:
            if job.operation == "stopMicrotechWorker":
                result = client.stop_microtech_worker()
            elif job.operation == "startMicrotechWorker":
                result = client.start_microtech_worker()
            elif job.operation == "enterMicrotechBackupMode":
                result = client.enter_microtech_backup_mode(
                    deadline_minutes=(job.request_payload or {}).get("deadlineMinutes"),
                    requested_by=str((job.context or {}).get("requested_by") or ""),
                )
            else:
                result = client.leave_microtech_backup_mode()
        except Exception as exc:
            MicrotechGraphQLJob.objects.filter(pk=job.pk).update(
                status=MicrotechGraphQLJob.Status.FAILED,
                error_message=str(exc),
                next_step="Die Wartungsoperation ist fehlgeschlagen.",
                completed_at=timezone.now(),
                next_poll_at=None,
                updated_at=timezone.now(),
            )
            raise

        # Das lokale Flag erst jetzt setzen bzw. loeschen: der Wrapper hat den
        # Zustand bestaetigt, vorher waere er nur behauptet.
        if job.operation == "enterMicrotechBackupMode":
            MicrotechBackupModeService.mark_entered(
                deadline_at=result.get("deadlineAt"),
                requested_by=str((job.context or {}).get("requested_by") or ""),
            )
        elif job.operation == "leaveMicrotechBackupMode":
            MicrotechBackupModeService.mark_left()

        now = timezone.now()
        MicrotechGraphQLJob.objects.filter(pk=job.pk).update(
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            result_payload=result,
            next_step=str(result.get("message") or "Wartungsoperation abgeschlossen."),
            completed_at=now,
            next_poll_at=None,
            updated_at=now,
        )
        return MicrotechGraphQLJob.objects.filter(pk=job.pk).first()

    def handle_webhook(self, payload: dict[str, Any]) -> MicrotechGraphQLJob:
        external_job_id = self._external_job_id_from_payload(payload)
        if not external_job_id:
            raise ValueError("Webhook payload does not contain jobId.")

        with transaction.atomic():
            job = (
                MicrotechGraphQLJob.objects.select_for_update()
                .filter(external_job_id=external_job_id)
                .first()
            )
            if job is None:
                raise MicrotechGraphQLJob.DoesNotExist(f"Unknown Microtech GraphQL jobId: {external_job_id}")
            if job.is_terminal:
                return job

            now = timezone.now()
            job.webhook_received_at = now
            remote_status = str(self._payload_value(payload, "status") or "").upper()
            if remote_status in self.REMOTE_SUCCESS:
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise ValueError("Erfolgreicher Microtech-Webhook enthält kein Ergebnis für die Continuation.")
                job.result_payload = result
            else:
                job.result_payload = payload
            self._apply_remote_status(job, payload)
            job.save()

        self._after_terminal_update(job.pk)
        return MicrotechGraphQLJob.objects.filter(pk=job.pk).first() or job

    def process_continuation(self, *, job_id: int, task_id: str) -> None:
        """Run exactly one claimed continuation.

        A Celery delivery is only allowed to run the handler when it owns the
        durable task id stored on the job.  A late duplicate delivery therefore
        becomes a no-op before it reaches a remote mutation.
        """
        task_id = str(task_id or "").strip()
        if not task_id:
            logger.warning("Continuation fuer Microtech GraphQL Job %s ohne Celery-Task-ID ignoriert.", job_id)
            return

        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().filter(pk=job_id).first()
            if job is None or job.status != MicrotechGraphQLJob.Status.SUCCEEDED:
                return
            continuation = str(job.continuation or "").strip()
            if not continuation:
                should_cleanup = job.delete_after_completion
                handler = None
            else:
                if (
                    job.continuation_status != MicrotechGraphQLJob.ContinuationStatus.DISPATCHED
                    or job.continuation_task_id != task_id
                ):
                    return
                handler = CONTINUATIONS.get(continuation)
                should_cleanup = False
                if handler is None:
                    job.continuation_status = MicrotechGraphQLJob.ContinuationStatus.FAILED
                    job.error_message = f"Keine Continuation fuer '{continuation}' registriert."
                    job.next_step = "Continuation fehlgeschlagen."
                    job.next_poll_at = None
                    job.continuation_completed_at = timezone.now()
                    job.continuation_lease_expires_at = None
                    job.save(
                        update_fields=(
                            "continuation_status",
                            "error_message",
                            "next_step",
                            "next_poll_at",
                            "continuation_completed_at",
                            "continuation_lease_expires_at",
                            "updated_at",
                        )
                    )
                    return

                now = timezone.now()
                job.continuation_status = MicrotechGraphQLJob.ContinuationStatus.RUNNING
                job.continuation_started_at = job.continuation_started_at or now
                job.continuation_heartbeat_at = now
                job.continuation_lease_expires_at = now + timedelta(
                    seconds=self._continuation_lease_seconds(job)
                )
                job.next_step = "Continuation laeuft."
                job.next_poll_at = None
                job.save(
                    update_fields=(
                        "continuation_status",
                        "continuation_started_at",
                        "continuation_heartbeat_at",
                        "continuation_lease_expires_at",
                        "next_step",
                        "next_poll_at",
                        "updated_at",
                    )
                )

        if handler is not None:
            if not self._acquire_continuation_lock(job_id=job_id):
                logger.warning("Continuation fuer Microtech GraphQL Job %s ist bereits durch einen Worker gesperrt.", job_id)
                return
            try:
                handler(job)
            except Exception as exc:
                MicrotechGraphQLJob.objects.filter(
                    pk=job_id,
                    continuation_task_id=task_id,
                    continuation_status=MicrotechGraphQLJob.ContinuationStatus.RUNNING,
                ).update(
                    continuation_status=MicrotechGraphQLJob.ContinuationStatus.FAILED,
                    error_message=str(exc),
                    next_step="Continuation fehlgeschlagen.",
                    next_poll_at=None,
                    continuation_completed_at=timezone.now(),
                    continuation_lease_expires_at=None,
                    updated_at=timezone.now(),
                )
                raise
            finally:
                self._release_continuation_lock(job_id=job_id)
            should_cleanup = job.delete_after_completion

        if should_cleanup:
            self.delete_job(job_id=job_id, delete_remote=True)
        elif handler is not None:
            MicrotechGraphQLJob.objects.filter(
                pk=job_id,
                continuation_task_id=task_id,
                continuation_status=MicrotechGraphQLJob.ContinuationStatus.RUNNING,
            ).update(
                continuation_status=MicrotechGraphQLJob.ContinuationStatus.COMPLETED,
                next_step="Continuation abgeschlossen.",
                next_poll_at=None,
                continuation_heartbeat_at=timezone.now(),
                continuation_completed_at=timezone.now(),
                continuation_lease_expires_at=None,
                updated_at=timezone.now(),
            )

    def heartbeat_continuation(self, *, job_id: int, task_id: str) -> bool:
        """Extend a running continuation lease only for its owning task."""
        task_id = str(task_id or "").strip()
        if not task_id:
            return False
        now = timezone.now()
        job = MicrotechGraphQLJob.objects.filter(
            pk=job_id,
            continuation_task_id=task_id,
            continuation_status=MicrotechGraphQLJob.ContinuationStatus.RUNNING,
        ).only("continuation", "context").first()
        if job is None:
            return False
        updated = MicrotechGraphQLJob.objects.filter(pk=job.pk, continuation_task_id=task_id).update(
            continuation_heartbeat_at=now,
            continuation_lease_expires_at=now + timedelta(seconds=self._continuation_lease_seconds(job)),
            updated_at=now,
        )
        return bool(updated)

    def poll_due_jobs(self, *, limit: int = 50) -> int:
        job_ids = self._claim_due_jobs(limit=limit)
        from microtech.tasks import poll_graphql_job

        for job_id in job_ids:
            poll_graphql_job.delay(job_id)
        remaining = max(0, limit - len(job_ids))
        continuation_ids = self._pending_continuation_ids(limit=remaining)
        dispatched_continuations = sum(
            1 for continuation_id in continuation_ids if self._dispatch_continuation(continuation_id)
        )
        return len(job_ids) + dispatched_continuations

    def _claim_due_jobs(self, *, limit: int) -> list[int]:
        """Reserviere faellige Jobs atomar und schiebe ihren naechsten Poll nach vorne.

        Der Claim verhindert, dass ueberlappende Beat-Laeufe denselben Job doppelt
        einreihen, bevor der dispatchte Poll ausgefuehrt wurde. ``skip_locked``
        laesst parallele Beat-Laeufe sich die Arbeit teilen statt sich zu blockieren.
        """
        now = timezone.now()
        with transaction.atomic():
            job_ids = list(
                MicrotechGraphQLJob.objects.select_for_update(**self._skip_locked_kwargs())
                .filter(status__in=self.LOCAL_ACTIVE)
                .filter(Q(next_poll_at__lte=now) | Q(next_poll_at__isnull=True))
                .order_by("next_poll_at", "created_at")
                .values_list("pk", flat=True)[:limit]
            )
            if job_ids:
                MicrotechGraphQLJob.objects.filter(pk__in=job_ids).update(
                    next_poll_at=now + timedelta(seconds=self.POLL_DISPATCH_BACKOFF_SECONDS),
                    updated_at=now,
                )
        return job_ids

    def _pending_continuation_ids(self, *, limit: int) -> list[int]:
        if limit <= 0:
            return []
        now = timezone.now()
        return list(
            MicrotechGraphQLJob.objects.filter(status=MicrotechGraphQLJob.Status.SUCCEEDED)
            .exclude(continuation="")
            .filter(
                Q(continuation_status=MicrotechGraphQLJob.ContinuationStatus.PENDING)
                | Q(
                    continuation_status=MicrotechGraphQLJob.ContinuationStatus.DISPATCHED,
                    continuation_lease_expires_at__lte=now,
                )
            )
            .order_by("continuation_lease_expires_at", "completed_at", "created_at")
            .values_list("pk", flat=True)[:limit]
        )

    @staticmethod
    def _skip_locked_kwargs() -> dict[str, bool]:
        if connection.features.has_select_for_update_skip_locked:
            return {"skip_locked": True}
        return {}

    def poll_job_once(self, *, job_id: int) -> bool:
        with transaction.atomic():
            job = (
                MicrotechGraphQLJob.objects.select_for_update(**self._skip_locked_kwargs())
                .filter(pk=job_id)
                .first()
            )
            if job is None or job.is_terminal or not job.external_job_id:
                return False
            job.attempt += 1
            job.last_polled_at = timezone.now()
            job.save(update_fields=("attempt", "last_polled_at", "updated_at"))
            attempt = job.attempt
            max_attempts = job.max_attempts

        client = MicrotechGraphQLClientService()
        try:
            remote = self._fetch_remote_job(client=client, job=job)
        except Exception as exc:
            self._handle_poll_failure(job_id=job_id, attempt=attempt, max_attempts=max_attempts, error=exc)
            return False

        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().get(pk=job_id)
            if job.is_terminal:
                return True
            job.result_payload = remote
            self._apply_remote_status(job, remote)
            if not job.is_terminal:
                if attempt >= max_attempts:
                    self._mark_exhausted(job, remote, attempt)
                else:
                    job.next_poll_at = self._reschedule_at(remote)
            job.save()

        self._after_terminal_update(job_id)
        return True

    def cancel_job(self, *, job_id: int) -> None:
        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().get(pk=job_id)
            if not job.can_cancel:
                return
            job.status = MicrotechGraphQLJob.Status.CANCEL_REQUESTED
            job.next_step = "Abbruch angefordert."
            job.save(update_fields=("status", "next_step", "updated_at"))

        try:
            if job.external_job_id and job.abort_strategy == MicrotechGraphQLJob.AbortStrategy.CANCEL_THEN_DELETE:
                MicrotechGraphQLClientService().cancel_job(job.external_job_id)
            self.delete_job(job_id=job_id, delete_remote=bool(job.external_job_id))
        except Exception as exc:
            MicrotechGraphQLJob.objects.filter(pk=job_id).update(
                status=MicrotechGraphQLJob.Status.FAILED,
                error_message=str(exc),
                completed_at=timezone.now(),
            )
            raise

    def delete_job(self, *, job_id: int, delete_remote: bool = True) -> bool:
        job = MicrotechGraphQLJob.objects.filter(pk=job_id).first()
        if job is None:
            return False

        if delete_remote and job.external_job_id and job.abort_strategy != MicrotechGraphQLJob.AbortStrategy.LOCAL_ONLY:
            try:
                MicrotechGraphQLClientService().delete_job(job.external_job_id)
            except GraphQLMicrotechError as exc:
                job.status = MicrotechGraphQLJob.Status.DELETE_FAILED
                job.error_message = str(exc)
                job.save(update_fields=("status", "error_message", "updated_at"))
                raise
            job.remote_deleted_at = timezone.now()
            job.save(update_fields=("remote_deleted_at", "updated_at"))

        self._delete_local_job_references(job)
        job.delete()
        return True

    def cleanup_old_jobs(
        self,
        *,
        max_age_days: int = 30,
        limit: int = 100,
        terminal_only: bool = True,
    ) -> dict[str, int]:
        """Loescht alte, lokal verfolgte GraphQL-Jobs remote und lokal.

        Abgeschlossene Jobs werden nach ``completed_at`` bewertet. Fuer alte
        ``DELETE_FAILED``-Eintraege ohne Abschlusszeitpunkt dient ``created_at``
        als Fallback. Mit ``terminal_only=False`` koennen bewusst auch alte,
        noch nicht abgeschlossene Jobs entfernt werden.
        """
        if max_age_days < 0:
            raise ValueError("max_age_days must be greater than or equal to zero.")
        if limit < 1:
            raise ValueError("limit must be greater than zero.")

        cutoff = timezone.now() - timedelta(days=max_age_days)
        jobs = MicrotechGraphQLJob.objects.all()
        if terminal_only:
            jobs = jobs.filter(status__in=self.TERMINAL_STATUSES).filter(
                Q(completed_at__lt=cutoff) | Q(completed_at__isnull=True, created_at__lt=cutoff)
            )
            jobs = jobs.order_by("completed_at", "created_at", "pk")
        else:
            jobs = jobs.filter(created_at__lt=cutoff).order_by("created_at", "pk")

        deleted = 0
        failed = 0
        job_ids = list(jobs.values_list("pk", flat=True)[:limit])
        for job_id in job_ids:
            try:
                if self.delete_job(job_id=job_id, delete_remote=True):
                    deleted += 1
            except Exception:
                failed += 1
                logger.exception("Alter Microtech GraphQL Job %s konnte nicht geloescht werden.", job_id)

        return {"deleted": deleted, "failed": failed}

    @staticmethod
    def _delete_local_job_references(job: MicrotechGraphQLJob) -> None:
        from orders.models import MicrotechOrderSyncWorkflow

        # A deleted or remote-lost job must not erase the business workflow.
        # The order reconciler can safely mark a workflow with no current job as
        # failed and decide whether to recover or resume it.
        MicrotechOrderSyncWorkflow.objects.filter(current_job=job).update(
            current_job=None,
            updated_at=timezone.now(),
        )

    @staticmethod
    def verify_webhook_signature(*, body: bytes, signature: str) -> bool:
        secret = str(getattr(settings, "MICROTECH_GRAPHQL_WEBHOOK_SECRET", "") or "").strip()
        if not secret:
            return True
        expected = hmac.new(secret.encode("utf-8"), body, "sha256").hexdigest()
        provided = str(signature or "").replace("sha256=", "").strip()
        return hmac.compare_digest(expected, provided)

    def _after_terminal_update(self, job_id: int) -> None:
        job = MicrotechGraphQLJob.objects.filter(pk=job_id).first()
        if job is None or not job.is_terminal:
            return
        if job.status == MicrotechGraphQLJob.Status.SUCCEEDED:
            if not job.continuation and job.delete_after_completion:
                self.delete_job(job_id=job_id, delete_remote=True)
                return
            if job.continuation:
                self._dispatch_continuation(job_id)
        elif job.status == MicrotechGraphQLJob.Status.CANCELLED and job.delete_after_completion:
            self.delete_job(job_id=job_id, delete_remote=True)

    def _dispatch_continuation(self, job_id: int) -> bool:
        """Atomically claim and publish one continuation exactly once.

        The generated Celery task id is stored before publishing.  If the
        process stops in the small publish window, the lease eventually makes
        the *unstarted* dispatch eligible again; a late old delivery no longer
        owns the persisted task id and exits without side effects.
        """
        now = timezone.now()
        task_id = str(uuid4())
        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().filter(pk=job_id).first()
            if (
                job is None
                or job.status != MicrotechGraphQLJob.Status.SUCCEEDED
                or not str(job.continuation or "").strip()
            ):
                return False

            can_claim = job.continuation_status == MicrotechGraphQLJob.ContinuationStatus.PENDING
            can_reclaim = (
                job.continuation_status == MicrotechGraphQLJob.ContinuationStatus.DISPATCHED
                and job.continuation_lease_expires_at is not None
                and job.continuation_lease_expires_at <= now
            )
            if not (can_claim or can_reclaim):
                return False
            if job.continuation_attempt >= job.continuation_max_attempts:
                job.continuation_status = MicrotechGraphQLJob.ContinuationStatus.FAILED
                job.error_message = "Continuation konnte nicht eingereiht werden: max. Versuche erreicht."
                job.next_step = "Continuation fehlgeschlagen."
                job.continuation_completed_at = now
                job.continuation_lease_expires_at = None
                job.save(
                    update_fields=(
                        "continuation_status",
                        "error_message",
                        "next_step",
                        "continuation_completed_at",
                        "continuation_lease_expires_at",
                        "updated_at",
                    )
                )
                return False

            job.continuation_status = MicrotechGraphQLJob.ContinuationStatus.DISPATCHED
            job.continuation_task_id = task_id
            job.continuation_dispatched_at = now
            job.continuation_started_at = None
            job.continuation_heartbeat_at = None
            job.continuation_completed_at = None
            job.continuation_lease_expires_at = now + timedelta(seconds=self._continuation_lease_seconds(job))
            job.continuation_attempt += 1
            job.next_step = "Continuation eingereiht."
            job.next_poll_at = None
            job.save(
                update_fields=(
                    "continuation_status",
                    "continuation_task_id",
                    "continuation_dispatched_at",
                    "continuation_started_at",
                    "continuation_heartbeat_at",
                    "continuation_completed_at",
                    "continuation_lease_expires_at",
                    "continuation_attempt",
                    "next_step",
                    "next_poll_at",
                    "updated_at",
                )
            )

        try:
            self._enqueue_continuation_task(job_id=job_id, task_id=task_id, queue=self._continuation_queue(job))
        except Exception:
            # The remote job has already completed. A known broker-publish
            # failure returns the continuation to PENDING immediately; an
            # unknown crash is recovered through the persisted lease above.
            MicrotechGraphQLJob.objects.filter(
                pk=job_id,
                continuation_task_id=task_id,
                continuation_status=MicrotechGraphQLJob.ContinuationStatus.DISPATCHED,
            ).update(
                continuation_status=MicrotechGraphQLJob.ContinuationStatus.PENDING,
                continuation_task_id="",
                next_step="Continuation ausfuehren.",
                continuation_dispatched_at=None,
                continuation_lease_expires_at=None,
                updated_at=timezone.now(),
            )
            logger.exception("Continuation für Microtech GraphQL Job %s konnte nicht eingereiht werden.", job_id)
            return False
        return True

    @classmethod
    def _continuation_queue(cls, job: MicrotechGraphQLJob) -> str:
        return cls.CONTINUATION_QUEUE_BY_NAME.get(str(job.continuation or "").strip(), "microtech")

    def _continuation_lease_seconds(self, job: MicrotechGraphQLJob) -> int:
        if self._continuation_queue(job) == "bulk":
            return self.BULK_CONTINUATION_LEASE_SECONDS
        return self.CONTINUATION_LEASE_SECONDS

    @staticmethod
    def _enqueue_continuation_task(*, job_id: int, task_id: str, queue: str) -> None:
        from microtech.tasks import (
            process_bulk_graphql_job_result,
            process_graphql_job_result,
            process_order_graphql_job_result,
        )

        task = {
            "orders": process_order_graphql_job_result,
            "bulk": process_bulk_graphql_job_result,
        }.get(queue, process_graphql_job_result)
        task.apply_async(args=(job_id,), task_id=task_id, queue=queue)

    @classmethod
    def _acquire_continuation_lock(cls, *, job_id: int) -> bool:
        if connection.vendor != "postgresql":
            return True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s, %s)",
                [cls.CONTINUATION_LOCK_NAMESPACE, int(job_id)],
            )
            row = cursor.fetchone()
        return bool(row and row[0])

    @classmethod
    def _release_continuation_lock(cls, *, job_id: int) -> None:
        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s, %s)",
                [cls.CONTINUATION_LOCK_NAMESPACE, int(job_id)],
            )

    def _apply_remote_status(self, job: MicrotechGraphQLJob, payload: dict[str, Any]) -> None:
        remote_status = str(self._payload_value(payload, "status") or "").upper()
        now = timezone.now()
        if remote_status in self.REMOTE_SUCCESS:
            job.status = MicrotechGraphQLJob.Status.SUCCEEDED
            job.completed_at = now
            job.next_step = "Continuation ausfuehren." if job.continuation else "Remote Job loeschen."
            return
        if remote_status in self.REMOTE_CANCELLED:
            job.status = MicrotechGraphQLJob.Status.CANCELLED
            job.completed_at = now
            job.next_step = "Job wurde abgebrochen."
            return
        if remote_status in self.REMOTE_FAILED:
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.completed_at = now
            job.error_message = str(
                self._payload_value(payload, "errorMessage")
                or self._payload_value(payload, "message")
                or "Microtech GraphQL Job fehlgeschlagen."
            )
            job.next_step = "Fehler pruefen."
            return
        job.status = MicrotechGraphQLJob.Status.RUNNING
        job.next_step = job.next_step or "Warte auf Microtech GraphQL Abschluss."

    @classmethod
    def _fetch_remote_job(cls, *, client: MicrotechGraphQLClientService, job: MicrotechGraphQLJob) -> dict[str, Any]:
        if job.kind == MicrotechGraphQLJob.Kind.DATASET_RECORDS:
            if job.operation == "searchCustomers":
                return client.customer_search_job(str(job.external_job_id))
            return client.dataset_job(str(job.external_job_id))
        if job.kind == MicrotechGraphQLJob.Kind.PRODUCT_READ:
            return client.product_list_job(str(job.external_job_id))
        if job.kind == MicrotechGraphQLJob.Kind.PRODUCT_UPDATE:
            return client.product_job(str(job.external_job_id))
        if job.kind in {MicrotechGraphQLJob.Kind.CUSTOMER_READ, MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT}:
            return client.customer_job(str(job.external_job_id))
        if job.kind in {MicrotechGraphQLJob.Kind.ORDER_READ, MicrotechGraphQLJob.Kind.ORDER_UPSERT}:
            return client.vorgang_job(str(job.external_job_id))
        return client.microtech_job(str(job.external_job_id))

    def _handle_poll_failure(self, *, job_id: int, attempt: int, max_attempts: int, error: Exception) -> None:
        now = timezone.now()
        if self._is_remote_job_missing(error) and self._recover_missing_remote_job(
            job_id=job_id,
            error_message=str(error),
        ):
            return
        if attempt >= max_attempts:
            MicrotechGraphQLJob.objects.filter(pk=job_id).update(
                status=MicrotechGraphQLJob.Status.FAILED,
                error_message=str(error),
                next_step="Poll-Fehler, max. Versuche erreicht.",
                next_poll_at=None,
                completed_at=now,
                updated_at=now,
            )
            return
        jitter = random.uniform(0, self.POLL_JITTER_SECONDS)
        MicrotechGraphQLJob.objects.filter(pk=job_id).update(
            error_message=str(error),
            next_poll_at=now + timedelta(seconds=self.POLL_ERROR_BACKOFF_SECONDS + jitter),
            updated_at=now,
        )

    @staticmethod
    def _is_remote_job_missing(error: Exception) -> bool:
        message = str(error or "").lower()
        missing = ("job not found", "unknown job", "job-id not found", "job id not found", "job nicht gefunden")
        return any(fragment in message for fragment in missing)

    def _recover_missing_remote_job(self, *, job_id: int, error_message: str) -> bool:
        """Recover a lost remote job only through an operation-specific path."""
        job = MicrotechGraphQLJob.objects.filter(pk=job_id).first()
        if job is None:
            return False

        from orders.models import MicrotechOrderSyncWorkflow

        workflow = MicrotechOrderSyncWorkflow.objects.filter(current_job_id=job.pk).first()
        if workflow is not None and workflow.current_step == "write_vorgang":
            from orders.services.order_sync_workflow import OrderSyncWorkflowService

            return OrderSyncWorkflowService().recover_missing_remote_job(
                workflow_id=workflow.pk,
                job_id=job.pk,
                error_message=error_message,
            )

        return self._resubmit_lost_remote_job(job=job, error_message=error_message)

    def _resubmit_lost_remote_job(self, *, job: MicrotechGraphQLJob, error_message: str) -> bool:
        """Re-submit only mutations with deterministic request semantics."""
        if job.remote_resubmit_attempt >= job.remote_resubmit_max_attempts:
            return False
        try:
            external_job_id, retry_after = self._submit_saved_request(job=job)
        except ValueError:
            # Unsupported creates are intentionally left for the workflow
            # reconciler instead of risking a duplicate remote mutation.
            return False
        except Exception:
            logger.exception("Remote-Jobverlust für Microtech GraphQL Job %s konnte nicht wiederhergestellt werden.", job.pk)
            return False

        now = timezone.now()
        with transaction.atomic():
            locked = MicrotechGraphQLJob.objects.select_for_update().filter(pk=job.pk).first()
            if locked is None or locked.is_terminal:
                return False
            history = list(locked.external_job_history or [])
            history.append(
                {
                    "external_job_id": locked.external_job_id or "",
                    "at": now.isoformat(),
                    "reason": "remote_job_not_found_resubmitted",
                    "message": str(error_message),
                    "replacement_external_job_id": str(external_job_id),
                }
            )
            locked.external_job_history = history
            locked.external_job_id = str(external_job_id)
            locked.status = MicrotechGraphQLJob.Status.WAITING_WEBHOOK
            locked.error_message = ""
            locked.next_step = "Remote-Job nach Verlust erneut eingereicht."
            locked.submitted_at = now
            locked.started_at = now
            locked.last_polled_at = None
            locked.next_poll_at = now + timedelta(seconds=max(int(retry_after), 30))
            locked.attempt = 0
            locked.remote_resubmit_attempt += 1
            locked.save(
                update_fields=(
                    "external_job_history",
                    "external_job_id",
                    "status",
                    "error_message",
                    "next_step",
                    "submitted_at",
                    "started_at",
                    "last_polled_at",
                    "next_poll_at",
                    "attempt",
                    "remote_resubmit_attempt",
                    "updated_at",
                )
            )
        logger.warning(
            "Microtech GraphQL Job %s remote neu eingereiht: %s -> %s.",
            job.pk,
            job.external_job_id,
            external_job_id,
        )
        return True

    @staticmethod
    def _submit_saved_request(*, job: MicrotechGraphQLJob) -> tuple[str, float]:
        """Map persisted request payloads to idempotent GraphQL submissions."""
        client = MicrotechGraphQLClientService()
        payload = dict(job.request_payload or {})
        operation = str(job.operation or "")
        if operation == "requestDatasetRecords":
            return client.submit_dataset_job(payload)
        if operation == "requestProducts":
            return client.submit_request_products(
                erp_numbers=payload.get("erpNumbers") or None,
                include_images=bool(payload.get("includeImages", True)),
            )
        if operation == "updateProduct":
            return client.submit_update_product(str(payload["erpNumber"]), dict(payload["input"]))
        if operation == "requestCustomer":
            return client.submit_request_customer(str(payload["customerNumber"]))
        if operation == "searchCustomers":
            return client.submit_search_customers(
                customer_number=str(payload.get("customer_number") or ""),
                email=str(payload.get("email") or ""),
                first_name=str(payload.get("first_name") or ""),
                last_name=str(payload.get("last_name") or ""),
                limit=int(payload.get("limit") or 20),
            )
        if operation == "upsertCustomer":
            return client.submit_upsert_customer(str(payload["customerNumber"]), dict(payload["input"]))
        if operation == "updateCustomer":
            return client.submit_update_customer(str(payload["customerNumber"]), dict(payload["input"]))
        if operation == "updatePostalAddress":
            return client.submit_update_postal_address(
                int(payload["addressNumber"]),
                int(payload["addressSubNumber"]),
                dict(payload["input"]),
            )
        if operation == "updateContactPerson":
            return client.submit_update_contact_person(
                int(payload["addressNumber"]),
                int(payload["addressSubNumber"]),
                int(payload["contactNumber"]),
                dict(payload["input"]),
            )
        if operation == "requestVorgang":
            return client.submit_request_vorgang(str(payload["belegNr"]))
        if operation == "updateVorgang":
            return client.submit_update_vorgang(str(payload["belegNr"]), dict(payload["input"]))
        raise ValueError(f"Remote resubmit is unsafe or unsupported for operation '{operation}'.")

    def _reschedule_at(self, remote: dict[str, Any]):
        retry_after = self._payload_value(remote, "retryAfterSeconds")
        try:
            base = int(retry_after)
        except (TypeError, ValueError):
            base = self.DEFAULT_POLL_INTERVAL_SECONDS
        base = max(base, self.MIN_POLL_INTERVAL_SECONDS)
        jitter = random.uniform(0, self.POLL_JITTER_SECONDS)
        return timezone.now() + timedelta(seconds=base + jitter)

    def _mark_exhausted(self, job: MicrotechGraphQLJob, remote: dict[str, Any], attempt: int) -> None:
        remote_status = str(self._payload_value(remote, "status") or "").upper() or "unbekannt"
        job.status = MicrotechGraphQLJob.Status.FAILED
        job.error_message = f"Job nach {attempt} Versuchen nicht abgeschlossen (Status: {remote_status})."
        job.next_step = "Max. Versuche erreicht."
        job.completed_at = timezone.now()
        job.next_poll_at = None

    @staticmethod
    def _external_job_id_from_payload(payload: dict[str, Any]) -> str:
        for key in ("jobId", "job_id", "externalJobId", "external_job_id"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        for value in payload.values():
            if isinstance(value, dict):
                nested = MicrotechJobSentinelService._external_job_id_from_payload(value)
                if nested:
                    return nested
        return ""

    @staticmethod
    def _payload_value(payload: dict[str, Any], key: str) -> Any:
        if key in payload:
            return payload.get(key)
        for value in payload.values():
            if isinstance(value, dict):
                nested = MicrotechJobSentinelService._payload_value(value, key)
                if nested not in (None, ""):
                    return nested
        return None

    @staticmethod
    def payload_from_body(body: bytes) -> dict[str, Any]:
        payload = json.loads(body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        return payload
