from __future__ import annotations

from celery import chain, shared_task
from django.utils import timezone

from ai.models import AIRewriteJob, AITranslationState
from ai.services import AIRewriteService, AITranslationService


@shared_task
def run_ai_rewrite_job(job_id: int) -> None:
    try:
        job = AIRewriteJob.objects.select_related("product", "category", "prompt", "provider").get(pk=job_id)
    except AIRewriteJob.DoesNotExist:
        return
    AIRewriteService().execute(job)


@shared_task(name="ai.queue_translation_scan")
def queue_ai_translation_scan(configuration_id: int | None = None) -> int:
    """Find changed fields and enqueue an intentionally serial translation chain."""
    state_ids = AITranslationService().queue_pending_translations(configuration_id=configuration_id)
    if not state_ids:
        return 0
    try:
        async_result = chain(*(run_ai_translation_state.si(state_id) for state_id in state_ids)).apply_async()
    except Exception as exc:  # noqa: BLE001 - scheduler must report an enqueue failure for every affected state.
        AITranslationState.objects.filter(pk__in=state_ids).update(
            status=AITranslationState.Status.FAILED,
            last_error=f"Celery enqueue failed: {exc}",
            updated_at=timezone.now(),
        )
        return 0
    AITranslationState.objects.filter(pk__in=state_ids, celery_task_id="").update(
        celery_task_id=getattr(async_result, "id", "") or "",
        updated_at=timezone.now(),
    )
    return len(state_ids)


@shared_task(bind=True, name="ai.translate_state", max_retries=3)
def run_ai_translation_state(self, state_id: int) -> str:
    """Execute one translation; transient provider failures are retried by Celery."""
    AITranslationState.objects.filter(pk=state_id).update(
        celery_task_id=getattr(self.request, "id", "") or "",
        updated_at=timezone.now(),
    )
    state = AITranslationService().translate_state(state_id=state_id)
    if state is None:
        return "missing"
    if state.status == AITranslationState.Status.PENDING:
        if self.request.retries >= self.max_retries:
            return state.status
        raise self.retry(
            exc=RuntimeError(state.last_error or "Quelltext hat sich geaendert."),
            countdown=60,
        )
    if state.status == AITranslationState.Status.FAILED:
        if self.request.retries >= self.max_retries:
            return state.status
        raise self.retry(
            exc=RuntimeError(state.last_error or "Uebersetzung fehlgeschlagen."),
            countdown=min(60 * (2 ** self.request.retries), 900),
        )
    return state.status
