from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone
from loguru import logger

from core.services import BaseService
from customer.models import Customer
from orders.models import Order
from orders.services.order_sync import OrderSyncService, _normalize_entity, _to_str
from shopware.services import CustomerService, OrderService


class OrderAddressBackfillService(BaseService):
    """Link missing order addresses after a verified customer address mapping."""

    model = Order

    def reconcile_customer(self, *, customer_id: int, address_id: int) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None or not customer.api_id:
            return {"orders_linked": 0, "addresses_linked": 0, "unresolved": [], "errors": []}

        orders = list(
            Order.objects.filter(customer=customer)
            .filter(Q(billing_address__isnull=True) | Q(shipping_address__isnull=True))
            .exclude(api_id="")
        )
        if not orders:
            return {"orders_linked": 0, "addresses_linked": 0, "unresolved": [], "errors": []}

        response = CustomerService().get_by_id(customer.api_id)
        customers = (response or {}).get("data") or []
        customer_payload = _normalize_entity(customers[0]) if customers else {}
        if _to_str(customer_payload.get("id")).lower() != customer.api_id.lower():
            raise ValueError("Shopware-Kunde für den Adressabgleich nicht eindeutig geladen.")

        order_service = OrderService()
        matcher = OrderSyncService()
        result: dict[str, Any] = {
            "orders_linked": 0, "addresses_linked": 0, "unresolved": [], "errors": [],
        }

        for order in orders:
            try:
                order_response = order_service.get_with_addresses_by_id(order.api_id)
                rows = (order_response or {}).get("data") or []
                order_data = _normalize_entity(rows[0]) if rows else {}
                order_customer = _normalize_entity(order_data.get("orderCustomer") or {})
                if (
                    _to_str(order_data.get("id")).lower() != order.api_id.lower()
                    or _to_str(order_customer.get("customerId")).lower() != customer.api_id.lower()
                ):
                    result["unresolved"].append(order.order_number)
                    continue

                billing_data = _normalize_entity(order_data.get("billingAddress") or {})
                deliveries = _normalize_entity(order_data.get("deliveries") or [])
                shipping_data = _normalize_entity(
                    (deliveries[0] or {}).get("shippingOrderAddress") or {}
                ) if deliveries else {}
                linked = 0
                for role, snapshot in (("billing", billing_data), ("shipping", shipping_data)):
                    if getattr(order, f"{role}_address_id") is not None or not snapshot:
                        continue
                    address = matcher._mapped_customer_address_for_order(
                        customer=customer,
                        order_address=snapshot,
                        customer_payload=customer_payload,
                        role=role,
                    )
                    if address is None or address.pk != address_id:
                        continue
                    linked += Order.objects.filter(
                        pk=order.pk, **{f"{role}_address__isnull": True}
                    ).update(**{f"{role}_address": address}, updated_at=timezone.now())

                if linked:
                    result["orders_linked"] += 1
                    result["addresses_linked"] += linked
                if linked < sum(
                    getattr(order, f"{role}_address_id") is None
                    for role in ("billing", "shipping")
                ):
                    result["unresolved"].append(order.order_number)
            except Exception as exc:
                logger.warning("Adressabgleich für Bestellung {} fehlgeschlagen: {}", order.order_number, exc)
                result["errors"].append(order.order_number)

        return result
