from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.services import BaseService
from microtech.models import MicrotechGraphQLJob
from microtech.services.graphql_client import GraphQLMicrotechError, MicrotechGraphQLClientService

ContinuationHandler = Callable[[MicrotechGraphQLJob], None]

CONTINUATIONS: dict[str, ContinuationHandler] = {}


def register_continuation(name: str, handler: ContinuationHandler) -> None:
    cleaned = str(name or "").strip()
    if not cleaned:
        raise ValueError("Continuation name is required.")
    CONTINUATIONS[cleaned] = handler


class MicrotechJobSentinelService(BaseService):
    model = MicrotechGraphQLJob

    REMOTE_SUCCESS = {"DONE", "SUCCEEDED", "SUCCESS"}
    REMOTE_FAILED = {"FAILED", "ERROR"}
    REMOTE_CANCELLED = {"CANCELLED", "CANCELED"}

    LOCAL_ACTIVE = {
        MicrotechGraphQLJob.Status.SUBMITTED,
        MicrotechGraphQLJob.Status.RUNNING,
        MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
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
            delete_after_completion=delete_after_completion,
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
            job.result_payload = payload
            self._apply_remote_status(job, payload)
            job.save()

        self._after_terminal_update(job.pk)
        return MicrotechGraphQLJob.objects.filter(pk=job.pk).first() or job

    def process_continuation(self, *, job_id: int) -> None:
        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().filter(pk=job_id).first()
            if job is None or job.status != MicrotechGraphQLJob.Status.SUCCEEDED:
                return
            continuation = str(job.continuation or "").strip()
            if not continuation:
                should_cleanup = job.delete_after_completion
                handler = None
            else:
                handler = CONTINUATIONS.get(continuation)
                should_cleanup = False
                if handler is None:
                    job.status = MicrotechGraphQLJob.Status.FAILED
                    job.error_message = f"Keine Continuation fuer '{continuation}' registriert."
                    job.completed_at = timezone.now()
                    job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
                    return

        if handler is not None:
            handler(job)
            should_cleanup = job.delete_after_completion

        if should_cleanup:
            self.delete_job(job_id=job_id, delete_remote=True)

    def poll_due_jobs(self, *, limit: int = 50) -> int:
        now = timezone.now()
        job_ids = list(
            MicrotechGraphQLJob.objects.filter(
                status__in=self.LOCAL_ACTIVE,
            )
            .filter(Q(next_poll_at__lte=now) | Q(next_poll_at__isnull=True))
            .order_by("next_poll_at", "created_at")
            .values_list("pk", flat=True)[:limit]
        )
        processed = 0
        for job_id in job_ids:
            if self.poll_job_once(job_id=job_id):
                processed += 1
        return processed

    def poll_job_once(self, *, job_id: int) -> bool:
        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().filter(pk=job_id).first()
            if job is None or job.is_terminal or not job.external_job_id:
                return False
            job.attempt += 1
            job.last_polled_at = timezone.now()
            job.save(update_fields=("attempt", "last_polled_at", "updated_at"))

        client = MicrotechGraphQLClientService()
        try:
            remote = self._fetch_remote_job(client=client, job=job)
        except Exception as exc:
            self._mark_poll_error(job_id=job_id, error=exc)
            return False

        with transaction.atomic():
            job = MicrotechGraphQLJob.objects.select_for_update().get(pk=job_id)
            if job.is_terminal:
                return True
            job.result_payload = remote
            self._apply_remote_status(job, remote)
            if not job.is_terminal:
                job.next_poll_at = timezone.now() + timedelta(seconds=60)
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

    def delete_job(self, *, job_id: int, delete_remote: bool = True) -> None:
        job = MicrotechGraphQLJob.objects.filter(pk=job_id).first()
        if job is None:
            return

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

        job.delete()

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
                from microtech.tasks import process_graphql_job_result

                process_graphql_job_result.delay(job_id)
        elif job.status == MicrotechGraphQLJob.Status.CANCELLED and job.delete_after_completion:
            self.delete_job(job_id=job_id, delete_remote=True)

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
            return client.dataset_job(str(job.external_job_id))
        if job.kind in {MicrotechGraphQLJob.Kind.PRODUCT_READ, MicrotechGraphQLJob.Kind.PRODUCT_UPDATE}:
            return client.product_job(str(job.external_job_id))
        if job.kind in {MicrotechGraphQLJob.Kind.CUSTOMER_READ, MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT}:
            return client.customer_job(str(job.external_job_id))
        if job.kind in {MicrotechGraphQLJob.Kind.ORDER_READ, MicrotechGraphQLJob.Kind.ORDER_UPSERT}:
            return client.vorgang_job(str(job.external_job_id))
        return client.microtech_job(str(job.external_job_id))

    @staticmethod
    def _mark_poll_error(*, job_id: int, error: Exception) -> None:
        next_poll_at = timezone.now() + timedelta(minutes=5)
        MicrotechGraphQLJob.objects.filter(pk=job_id).update(
            error_message=str(error),
            next_poll_at=next_poll_at,
        )

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
