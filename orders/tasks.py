from __future__ import annotations

from collections.abc import Sequence

from celery import current_task, shared_task
from django.core.management import call_command

from core.live_events import emit_event, emit_run_finished, emit_run_started


def _run_id() -> str:
    return getattr(getattr(current_task, "request", None), "id", "") or ""


@shared_task(name="microtech.reconcile_order_sync_workflows")
def reconcile_order_sync_workflows() -> int:
    from orders.services.order_sync_workflow import OrderSyncWorkflowService

    return OrderSyncWorkflowService().reconcile_failures()


def register_order_sync_continuations() -> None:
    from microtech.services import register_continuation
    from orders.services.order_sync_workflow import CONTINUATION_NAME, OrderSyncWorkflowService

    register_continuation(CONTINUATION_NAME, OrderSyncWorkflowService().advance)


register_order_sync_continuations()


@shared_task(name="orders.shopware_sync_open_orders")
def shopware_sync_open_orders(
    *,
    sales_channel_ids: Sequence[str] | None = None,
    limit_orders: int | None = None,
) -> None:
    command_options = {"limit_orders": limit_orders}
    for sales_channel_id in sales_channel_ids or []:
        value = str(sales_channel_id).strip()
        if value:
            command_options.setdefault("sales_channel_id", []).append(value)
    task_name = "orders.shopware_sync_open_orders"
    run_id = _run_id()
    emit_run_started(task_name, run_id, "Offene Bestellungen von Shopware synchronisieren")
    try:
        call_command("shopware_sync_open_orders", **command_options)
    except Exception as exc:
        emit_run_finished(task_name, run_id, f"Fehlgeschlagen: {exc}")
        raise
    emit_run_finished(task_name, run_id, "Offene Bestellungen synchronisiert")


@shared_task(name="orders.microtech_order_upsert")
def microtech_order_upsert(
    order_number: str = "",
    *,
    order_id: int | None = None,
    log_file: str = "",
) -> None:
    args = [order_number.strip()] if order_number.strip() else []
    task_name = "orders.microtech_order_upsert"
    run_id = _run_id()
    entity = order_number.strip() or (str(order_id) if order_id else "")
    try:
        call_command("microtech_order_upsert", *args, id=order_id, log_file=log_file)
    except Exception as exc:
        emit_event(task_name, entity=entity, step="→ microtech", status="error",
                   summary=f"Bestellung {entity} nach Microtech fehlgeschlagen: {exc}",
                   run_id=run_id, target="microtech", payload={"error": str(exc)})
        raise
    emit_event(task_name, entity=entity, step="→ microtech", status="ok",
               summary=f"Bestellung {entity} nach Microtech geschrieben",
               run_id=run_id, target="microtech")
