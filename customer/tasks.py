from __future__ import annotations

from celery import current_task, shared_task
from django.core.management import call_command

from core.live_events import emit_event


@shared_task(name="customer.microtech_customer_upsert")
def microtech_customer_upsert(
    erp_nr: str = "",
    *,
    customer_id: int | None = None,
) -> None:
    args = [erp_nr.strip()] if erp_nr.strip() else []
    task_name = "customer.microtech_customer_upsert"
    run_id = getattr(getattr(current_task, "request", None), "id", "") or ""
    entity = erp_nr.strip() or (str(customer_id) if customer_id else "")
    try:
        call_command("microtech_customer_upsert", *args, id=customer_id)
    except Exception as exc:
        emit_event(task_name, entity=entity, step="→ microtech", status="error",
                   summary=f"Kunde {entity} nach Microtech fehlgeschlagen: {exc}",
                   run_id=run_id, target="microtech", payload={"error": str(exc)})
        raise
    emit_event(task_name, entity=entity, step="→ microtech", status="ok",
               summary=f"Kunde {entity} nach Microtech geschrieben",
               run_id=run_id, target="microtech")


@shared_task(name="customer.microtech_customer_lookup")
def microtech_customer_lookup(erp_nr: str = "") -> None:
    cleaned_erp_nr = (erp_nr or "").strip()
    if not cleaned_erp_nr:
        raise ValueError("erp_nr is required.")
    call_command("microtech_customer_lookup", cleaned_erp_nr)
