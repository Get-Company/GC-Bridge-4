from __future__ import annotations

from celery import current_task, shared_task
from django.core.management import call_command

from core.live_events import emit_run_finished, emit_run_started


@shared_task(name="newsletter.shopware_sync_recipients")
def shopware_sync_recipients(
    *,
    limit: int | None = None,
    page_size: int = 100,
    status: str = "",
    email: str = "",
    mark_missing: bool = False,
) -> None:
    task_name = "newsletter.shopware_sync_recipients"
    run_id = getattr(getattr(current_task, "request", None), "id", "") or ""
    emit_run_started(task_name, run_id, "Newsletter-Empfänger mit Shopware synchronisieren")
    try:
        call_command(
            "shopware_sync_newsletter_recipients",
            limit=limit,
            page_size=page_size,
            status=status,
            email=email,
            mark_missing=mark_missing,
        )
    except Exception as exc:
        emit_run_finished(task_name, run_id, f"Fehlgeschlagen: {exc}")
        raise
    emit_run_finished(task_name, run_id, "Newsletter-Empfänger synchronisiert")
