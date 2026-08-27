from __future__ import annotations

from datetime import timedelta
from typing import Any

from celery import current_app
from django.db.models import Count, Q
from django.utils import timezone

from core.services import BaseService
from microtech.models import MicrotechGraphQLJob, MicrotechSettings
from microtech.services.graphql_client import MicrotechGraphQLClientService
from microtech.services.job_sentinel import MicrotechJobSentinelService
from orders.models import MicrotechOrderSyncWorkflow
from orders.services.order_sync_workflow import OrderSyncWorkflowService


class MicrotechMcpOperationsService(BaseService):
    """Provides the narrowly-scoped diagnostics and recovery operations used by the MCP servers."""

    model = MicrotechGraphQLJob

    ACTIVE_JOB_STATUSES = (
        MicrotechGraphQLJob.Status.QUEUED,
        MicrotechGraphQLJob.Status.SUBMITTED,
        MicrotechGraphQLJob.Status.RUNNING,
        MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
        MicrotechGraphQLJob.Status.CANCEL_REQUESTED,
    )

    def bridge_diagnosis(self, *, stale_after_minutes: int = 15, limit: int = 20) -> dict[str, Any]:
        """Return queue, workflow, Celery and remote-worker state without changing it."""
        stale_after_minutes = self._bounded_int(stale_after_minutes, minimum=1, maximum=1_440)
        limit = self._bounded_int(limit, minimum=1, maximum=100)
        now = timezone.now()
        stale_before = now - timedelta(minutes=stale_after_minutes)

        status_counts = {
            row["status"]: row["total"]
            for row in MicrotechGraphQLJob.objects.values("status").annotate(total=Count("id"))
        }
        stale_jobs = list(
            MicrotechGraphQLJob.objects.filter(status__in=self.ACTIVE_JOB_STATUSES)
            .filter(
                Q(started_at__lt=stale_before)
                | Q(started_at__isnull=True, submitted_at__lt=stale_before)
                | Q(started_at__isnull=True, submitted_at__isnull=True, created_at__lt=stale_before)
            )
            .order_by("created_at")[:limit]
        )
        stalled_workflows = list(
            MicrotechOrderSyncWorkflow.objects.filter(
                status__in=(
                    MicrotechOrderSyncWorkflow.Status.PENDING,
                    MicrotechOrderSyncWorkflow.Status.RUNNING,
                    MicrotechOrderSyncWorkflow.Status.WAITING,
                    MicrotechOrderSyncWorkflow.Status.FAILED,
                )
            )
            .select_related("current_job")
            .order_by("updated_at")[:limit]
        )
        settings_row = (
            MicrotechSettings.objects.filter(pk=1)
            .values(
                "backup_mode_active",
                "backup_mode_entered_at",
                "backup_mode_deadline",
                "backup_mode_started_by",
            )
            .first()
        )
        graphql = self.graphql_status()
        result = {
            "checked_at": self._timestamp(now),
            "queue": {
                "status_counts": status_counts,
                "stale_after_minutes": stale_after_minutes,
                "stale_jobs": [self._job_summary(job, now=now) for job in stale_jobs],
            },
            "order_workflows": [self._workflow_summary(workflow) for workflow in stalled_workflows],
            "celery": self._celery_status(),
            "graphql": graphql,
            "local_backup_mode": self._backup_mode_summary(settings_row),
        }
        result["recommended_actions"] = self._recommended_actions(result)
        return result

    def graphql_status(self) -> dict[str, Any]:
        """Read liveness, worker state and backup mode from the GraphQL wrapper."""
        client = MicrotechGraphQLClientService()
        result: dict[str, Any] = {}
        for label, call in (
            ("health", client.health),
            ("worker", client.microtech_worker_status),
            ("backup_mode", client.microtech_backup_mode),
        ):
            try:
                result[label] = call()
            except Exception as exc:  # Network and remote-service errors are diagnostic output.
                result[label] = {"available": False, "error": str(exc)}
        return result

    def job_diagnosis(self, *, job_id: int) -> dict[str, Any]:
        """Explain one local job and compare it with its remote GraphQL status."""
        job = MicrotechGraphQLJob.objects.get(pk=job_id)
        now = timezone.now()
        result: dict[str, Any] = {
            "job": self._job_summary(job, now=now, include_context=True),
            "workflow": self._workflow_for_job(job.pk),
            "remote": self._remote_status(job),
        }
        result["recommended_actions"] = self._job_recommendations(job=job, remote=result["remote"])
        return result

    def workflow_diagnosis(self, *, workflow_id: int) -> dict[str, Any]:
        """Explain the current workflow step, linked job and safe recovery choices."""
        workflow = MicrotechOrderSyncWorkflow.objects.select_related("current_job").get(pk=workflow_id)
        job = workflow.current_job
        remote = self._remote_status(job) if job is not None else {"available": False, "reason": "Kein aktueller Job"}
        result: dict[str, Any] = {
            "workflow": self._workflow_summary(workflow, include_steps=True),
            "current_job": self._job_summary(job, now=timezone.now(), include_context=True) if job else None,
            "remote": remote,
        }
        result["recommended_actions"] = self._workflow_recommendations(workflow=workflow, remote=remote)
        return result

    def poll_job_now(self, *, job_id: int, confirmation: str) -> dict[str, Any]:
        """Force one sentinel poll. Terminal success can enqueue the existing continuation."""
        self._require_confirmation(confirmation, "POLL")
        polled = MicrotechJobSentinelService().poll_job_once(job_id=job_id)
        job = MicrotechGraphQLJob.objects.get(pk=job_id)
        return {"polled": polled, "job": self._job_summary(job, now=timezone.now(), include_context=True)}

    def reconcile_order_workflows(self, *, confirmation: str) -> dict[str, Any]:
        """Run the existing reconciliation logic for failed or orphaned order workflows."""
        self._require_confirmation(confirmation, "ABGLEICH")
        changed = OrderSyncWorkflowService().reconcile_failures()
        return {"reconciled_workflows": changed}

    def resume_order_workflow(self, *, workflow_id: int, confirmation: str) -> dict[str, Any]:
        """Resume a definitively failed workflow at its current step."""
        self._require_confirmation(confirmation, "FORTSETZEN")
        workflow = MicrotechOrderSyncWorkflow.objects.get(pk=workflow_id)
        job = OrderSyncWorkflowService().resume(workflow)
        workflow.refresh_from_db()
        return {
            "workflow": self._workflow_summary(workflow, include_steps=True),
            "submitted_job": self._job_summary(job, now=timezone.now(), include_context=True) if job else None,
        }

    def abort_order_workflow(self, *, workflow_id: int, reason: str, confirmation: str) -> dict[str, Any]:
        """Abort a workflow locally when its remote job is unavailable; this does not cancel remote work."""
        self._require_confirmation(confirmation, "WORKFLOW ABBRECHEN")
        workflow = MicrotechOrderSyncWorkflow.objects.get(pk=workflow_id)
        aborted = OrderSyncWorkflowService().abort(workflow, reason=reason.strip())
        workflow.refresh_from_db()
        return {"aborted": aborted, "workflow": self._workflow_summary(workflow, include_steps=True)}

    def restart_order_workflow(self, *, workflow_id: int, confirmation: str) -> dict[str, Any]:
        """Abort locally and start the order from scratch only after remote status is unavailable."""
        self._require_confirmation(confirmation, "NEUSTARTEN")
        workflow = MicrotechOrderSyncWorkflow.objects.get(pk=workflow_id)
        restarted = OrderSyncWorkflowService().restart(workflow)
        return {
            "restarted": self._workflow_summary(restarted, include_steps=True) if restarted else None,
            "warning": "Ein Neustart kann doppelte Remote-Schreibvorgänge erzeugen, falls der alte Remote-Job doch noch endet.",
        }

    def cancel_job(self, *, job_id: int, confirmation: str) -> dict[str, Any]:
        """Cancel and delete a local/remote job using the existing sentinel behaviour."""
        self._require_confirmation(confirmation, "JOB ABBRECHEN")
        job = MicrotechGraphQLJob.objects.get(pk=job_id)
        external_job_id = job.external_job_id
        MicrotechJobSentinelService().cancel_job(job_id=job_id)
        return {
            "cancelled": True,
            "local_job_deleted": not MicrotechGraphQLJob.objects.filter(pk=job_id).exists(),
            "external_job_id": external_job_id,
        }

    def start_microtech_worker(self, *, confirmation: str) -> dict[str, Any]:
        """Queue the existing audited worker-start operation through Celery."""
        self._require_confirmation(confirmation, "WORKER STARTEN")
        job = MicrotechJobSentinelService().enqueue_microtech_worker_operation(
            operation="startMicrotechWorker",
            context={"source": "mcp", "requested_by": "mcp"},
        )
        return {"maintenance_job": self._job_summary(job, now=timezone.now(), include_context=True)}

    def fetch_customer(self, *, customer_number: str, timeout_seconds: int = 45) -> dict[str, Any]:
        """Fetch one customer through the GraphQL read queue without changing customer data."""
        client = MicrotechGraphQLClientService()
        job_id, retry_after = client.submit_request_customer(customer_number.strip())
        result = client.poll_job(
            job_id,
            query_job=client.customer_job,
            retry_after=retry_after,
            timeout=self._bounded_int(timeout_seconds, minimum=5, maximum=120),
        )
        return {"job_id": job_id, "result": result}

    def fetch_product(self, *, erp_number: str, timeout_seconds: int = 45) -> dict[str, Any]:
        """Fetch one product through a temporary GraphQL read job without changing product data."""
        client = MicrotechGraphQLClientService()
        job_id, retry_after = client.submit_request_products(erp_numbers=[erp_number.strip()], include_images=False)
        result = client.poll_job(
            job_id,
            query_job=client.product_list_job,
            retry_after=retry_after,
            timeout=self._bounded_int(timeout_seconds, minimum=5, maximum=120),
        )
        return {"job_id": job_id, "result": result}

    def fetch_order(self, *, beleg_nr: str, timeout_seconds: int = 45) -> dict[str, Any]:
        """Fetch one Microtech Vorgang through the GraphQL read queue without changing order data."""
        client = MicrotechGraphQLClientService()
        job_id, retry_after = client.submit_request_vorgang(beleg_nr.strip())
        result = client.poll_job(
            job_id,
            query_job=client.vorgang_job,
            retry_after=retry_after,
            timeout=self._bounded_int(timeout_seconds, minimum=5, maximum=120),
        )
        return {"job_id": job_id, "result": result}

    @staticmethod
    def _bounded_int(value: int, *, minimum: int, maximum: int) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Ungültige Zahl: {value!r}") from exc
        return min(max(numeric, minimum), maximum)

    @staticmethod
    def _require_confirmation(value: str, expected: str) -> None:
        if str(value or "").strip().upper() != expected:
            raise ValueError(f"Bestätigung erforderlich: confirmation muss exakt '{expected}' sein.")

    @staticmethod
    def _timestamp(value) -> str | None:
        return value.isoformat() if value else None

    def _job_summary(
        self,
        job: MicrotechGraphQLJob | None,
        *,
        now,
        include_context: bool = False,
    ) -> dict[str, Any] | None:
        if job is None:
            return None
        started = job.started_at or job.submitted_at or job.created_at
        result: dict[str, Any] = {
            "id": job.pk,
            "kind": job.kind,
            "operation": job.operation,
            "status": job.status,
            "external_job_id": job.external_job_id,
            "attempt": job.attempt,
            "max_attempts": job.max_attempts,
            "next_step": job.next_step,
            "error_message": job.error_message,
            "created_at": self._timestamp(job.created_at),
            "submitted_at": self._timestamp(job.submitted_at),
            "started_at": self._timestamp(job.started_at),
            "completed_at": self._timestamp(job.completed_at),
            "last_polled_at": self._timestamp(job.last_polled_at),
            "next_poll_at": self._timestamp(job.next_poll_at),
            "age_seconds": int((now - started).total_seconds()) if started else None,
        }
        if include_context:
            context = job.context or {}
            result["context"] = {
                key: context[key]
                for key in ("source", "workflow_id", "step", "order_id", "requested_by")
                if key in context
            }
        return result

    def _workflow_summary(
        self,
        workflow: MicrotechOrderSyncWorkflow | None,
        *,
        include_steps: bool = False,
    ) -> dict[str, Any] | None:
        if workflow is None:
            return None
        result: dict[str, Any] = {
            "id": workflow.pk,
            "order_id": workflow.order_id,
            "status": workflow.status,
            "current_step": workflow.current_step,
            "current_job_id": workflow.current_job_id,
            "error_message": workflow.error_message,
            "created_at": self._timestamp(workflow.created_at),
            "updated_at": self._timestamp(workflow.updated_at),
        }
        if include_steps:
            result["step_log"] = workflow.step_log or []
        return result

    def _workflow_for_job(self, job_id: int) -> dict[str, Any] | None:
        workflow = MicrotechOrderSyncWorkflow.objects.select_related("current_job").filter(current_job_id=job_id).first()
        return self._workflow_summary(workflow, include_steps=True)

    def _remote_status(self, job: MicrotechGraphQLJob | None) -> dict[str, Any]:
        if job is None:
            return {"available": False, "reason": "Kein lokaler Job"}
        if not job.external_job_id:
            return {"available": False, "reason": "Keine externe GraphQL-Job-ID"}
        try:
            return {
                "available": True,
                "result": MicrotechJobSentinelService._fetch_remote_job(
                    client=MicrotechGraphQLClientService(),
                    job=job,
                ),
            }
        except Exception as exc:  # Remote failures are the core diagnosis result.
            return {"available": False, "error": str(exc)}

    @staticmethod
    def _celery_status() -> dict[str, Any]:
        try:
            inspector = current_app.control.inspect(timeout=1.0)
            active = inspector.active() or {}
            scheduled = inspector.scheduled() or {}
            return {
                "available": True,
                "workers": sorted(set(active) | set(scheduled)),
                "active_tasks": {worker: len(tasks) for worker, tasks in active.items()},
                "scheduled_tasks": {worker: len(tasks) for worker, tasks in scheduled.items()},
            }
        except Exception as exc:  # A missing broker/worker is a valid diagnosis result.
            return {"available": False, "error": str(exc)}

    def _backup_mode_summary(self, settings_row: dict[str, Any] | None) -> dict[str, Any]:
        if settings_row is None:
            return {"configured": False}
        return {
            "configured": True,
            "active": bool(settings_row["backup_mode_active"]),
            "entered_at": self._timestamp(settings_row["backup_mode_entered_at"]),
            "deadline": self._timestamp(settings_row["backup_mode_deadline"]),
            "started_by": settings_row["backup_mode_started_by"],
        }

    @staticmethod
    def _recommended_actions(result: dict[str, Any]) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        worker = ((result.get("graphql") or {}).get("worker") or {}).get("worker") or {}
        if worker and not worker.get("running"):
            actions.append(
                {
                    "tool": "start_microtech_worker",
                    "reason": "Der GraphQL-Wrapper meldet den Microtech-Worker als nicht laufend.",
                }
            )
        if (result.get("queue") or {}).get("stale_jobs"):
            actions.append(
                {
                    "tool": "get_job_diagnosis",
                    "reason": "Es gibt überfällige lokale Jobs. Erst den Remote-Status und die Fehlermeldung prüfen.",
                }
            )
        if any(item.get("status") == MicrotechOrderSyncWorkflow.Status.FAILED for item in result.get("order_workflows") or []):
            actions.append(
                {
                    "tool": "get_order_workflow_diagnosis",
                    "reason": "Mindestens ein Order-Workflow ist fehlgeschlagen; vor einem Resume den letzten Remote-Status prüfen.",
                }
            )
        if not actions:
            actions.append({"tool": "get_bridge_diagnosis", "reason": "Keine unmittelbare Recovery-Aktion erkannt."})
        return actions

    @staticmethod
    def _job_recommendations(*, job: MicrotechGraphQLJob, remote: dict[str, Any]) -> list[dict[str, str]]:
        if not remote.get("available"):
            return [
                {
                    "tool": "start_microtech_worker",
                    "reason": "Der Remote-Status ist nicht erreichbar; Worker und GraphQL-Verbindung prüfen.",
                }
            ]
        if job.status in MicrotechJobSentinelService.LOCAL_ACTIVE:
            return [
                {
                    "tool": "poll_job_now",
                    "reason": "Der Job ist aktiv. Ein kontrollierter Einzel-Poll übernimmt einen bereits fertigen Remote-Status.",
                }
            ]
        if job.status == MicrotechGraphQLJob.Status.FAILED:
            return [
                {
                    "tool": "get_order_workflow_diagnosis",
                    "reason": "Bei einem zugehörigen Workflow zuerst dessen aktuellen Schritt und die Fehlerursache prüfen.",
                }
            ]
        return [{"tool": "get_job_diagnosis", "reason": "Der Job ist bereits terminal; keine automatische Aktion vorgeschlagen."}]

    @staticmethod
    def _workflow_recommendations(
        *,
        workflow: MicrotechOrderSyncWorkflow,
        remote: dict[str, Any],
    ) -> list[dict[str, str]]:
        if workflow.status == MicrotechOrderSyncWorkflow.Status.FAILED:
            return [
                {
                    "tool": "resume_order_workflow",
                    "reason": "Der Workflow ist fehlgeschlagen. Fortsetzen nur, wenn der Remote-Job definitiv fehlgeschlagen ist.",
                }
            ]
        if workflow.status == MicrotechOrderSyncWorkflow.Status.WAITING and not remote.get("available"):
            return [
                {
                    "tool": "abort_order_workflow",
                    "reason": "Der Workflow wartet, aber der Remote-Status ist nicht erreichbar. Lokaler Abbruch erst nach Prüfung des Remote-Systems.",
                }
            ]
        return [{"tool": "get_order_workflow_diagnosis", "reason": "Vor einer Änderung ist keine Recovery-Aktion erforderlich."}]
