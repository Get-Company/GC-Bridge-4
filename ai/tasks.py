from __future__ import annotations

from celery import shared_task

from ai.models import AIRewriteJob
from ai.services import AIRewriteService


@shared_task
def run_ai_rewrite_job(job_id: int) -> None:
    try:
        job = AIRewriteJob.objects.select_related("product", "category", "prompt", "provider").get(pk=job_id)
    except AIRewriteJob.DoesNotExist:
        return
    AIRewriteService().execute(job)
