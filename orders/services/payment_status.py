from __future__ import annotations

from typing import Any

from django.utils import timezone
from loguru import logger

from core.services import BaseService
from orders.models import Order
from orders.services.order_sync import OrderSyncService, _normalize_entity, _to_str
from shopware.services import OrderService


class OrderPaymentStatusService(BaseService):
    """Refresh payment data of imported orders without reimporting the orders."""

    model = Order
    payment_fields = (
        "payment_state", "api_transaction_id", "paypal_id",
        "paypal_transaction_id", "payment_method",
    )

    def sync(self, *, dry_run: bool = False, batch_size: int = 100) -> dict[str, int]:
        if not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100.")
        orders = list(
            self.get_queryset().exclude(api_id="").order_by("pk").values(
                "pk", "api_id", *self.payment_fields,
            )
        )
        summary = dict.fromkeys(
            ("orders_seen", "orders_updated", "orders_unchanged", "orders_missing", "orders_failed"), 0,
        )
        if not orders:
            return summary
        service = OrderService()
        for start in range(0, len(orders), batch_size):
            batch = orders[start:start + batch_size]
            summary["orders_seen"] += len(batch)
            try:
                response = service.request_post("/search/order", payload={
                    "ids": [order["api_id"] for order in batch],
                    "limit": len(batch),
                    "associations": {"transactions": {"associations": {
                        "stateMachineState": {}, "paymentMethod": {},
                    }}},
                    "includes": {
                        "order": ["id", "primaryOrderTransactionId", "transactions"],
                        "order_transaction": [
                            "id", "createdAt", "stateMachineState", "paymentMethod", "customFields",
                        ],
                        "state_machine_state": ["technicalName"],
                        "payment_method": ["name"],
                    },
                })
                remote = {row["id"]: row for row in self._entities(response)}
            except Exception:
                logger.exception("Shopware-Zahlungsstatus: Batch-Abruf fehlgeschlagen.")
                summary["orders_failed"] += len(batch)
                continue
            for order in batch:
                row = remote.get(order["api_id"])
                if row is None:
                    summary["orders_missing"] += 1
                    continue
                payment = self._payment(row, tracked_id=order["api_transaction_id"])
                state = _to_str((payment.get("stateMachineState") or {}).get("technicalName"))
                if not payment.get("id") or not state:
                    logger.error("Kein eindeutiger Zahlungsstatus fuer Shopware-Bestellung {}.", order["api_id"])
                    summary["orders_failed"] += 1
                    continue
                values = {
                    "payment_state": state,
                    "api_transaction_id": payment["id"],
                    "paypal_id": OrderSyncService._paypal_id(payment),
                    "paypal_transaction_id": OrderSyncService._paypal_transaction_id(payment),
                }
                method = _to_str((payment.get("paymentMethod") or {}).get("name"))
                if method:
                    values["payment_method"] = method
                changes = {key: value for key, value in values.items() if order[key] != value}
                if not changes:
                    summary["orders_unchanged"] += 1
                    continue
                if dry_run:
                    summary["orders_updated"] += 1
                    continue
                # Do not overwrite an import or manual refresh completed during the API request.
                updated = Order.objects.filter(
                    pk=order["pk"], api_id=order["api_id"],
                    **{key: order[key] for key in self.payment_fields},
                ).update(**changes, updated_at=timezone.now())
                summary["orders_updated" if updated else "orders_unchanged"] += 1
        return summary

    @staticmethod
    def _entities(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            payload = payload.get("data", [])
        return _normalize_entity(payload) if isinstance(payload, list) else []

    @classmethod
    def _payment(cls, order: dict[str, Any], *, tracked_id: str) -> dict[str, Any]:
        payments = cls._entities(order.get("transactions") or [])
        primary_id = _to_str(order.get("primaryOrderTransactionId"))
        if primary_id:
            return next((p for p in payments if p.get("id") == primary_id), {})
        # Older Shopware versions may not expose a primary transaction.
        if len(payments) == 1:
            return payments[0]
        return next((p for p in payments if p.get("id") == tracked_id), {})
