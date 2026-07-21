from __future__ import annotations

from collections.abc import Sequence

from celery import current_task, shared_task
from django.core.management import call_command

from core.live_events import emit_run_finished, emit_run_started


def _clean_erp_nrs(erp_nrs: Sequence[str] | None) -> list[str]:
    return [str(erp_nr).strip() for erp_nr in (erp_nrs or []) if str(erp_nr).strip()]


@shared_task(name="shopware.shopware5_sync_products")
def shopware5_sync_products(
    erp_nrs: Sequence[str] | None = None,
    *,
    limit: int | None = None,
    batch_size: int = 50,
    active_only: bool = False,
) -> dict | None:
    command_args = _clean_erp_nrs(erp_nrs)
    command_options = {
        "limit": limit,
        "batch_size": batch_size,
        "active_only": active_only,
    }
    task_name = "shopware.shopware5_sync_products"
    run_id = getattr(getattr(current_task, "request", None), "id", "") or ""
    scope = f"{len(command_args)} Produkte" if command_args else "alle Produkte"
    emit_run_started(task_name, run_id, f"Shopware5-Sync gestartet ({scope})")
    try:
        result = call_command("shopware5_sync_products", *command_args, **command_options)
    except Exception as exc:
        emit_run_finished(task_name, run_id, f"Fehlgeschlagen: {exc}")
        raise
    emit_run_finished(task_name, run_id, "Shopware5-Sync abgeschlossen", stats=result if isinstance(result, dict) else None)
    return result
