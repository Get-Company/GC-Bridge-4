from __future__ import annotations

from typing import Any

from loguru import logger

from .shopware6 import Criteria, EqualsFilter, Shopware6Service


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


DEFAULT_TRANSITION_ACTIONS: dict[str, list[str]] = {
    # Based on common Shopware state machine actions.
    "order": ["process", "complete", "cancel", "reopen"],
    "delivery": ["ship", "ship_partially", "cancel", "reopen", "retour", "retour_partially"],
    "payment": [
        "do_pay",
        "paid",
        "paid_partially",
        "authorize",
        "remind",
        "refund",
        "refund_partially",
        "cancel",
        "fail",
        "reopen",
    ],
}


class OrderService(Shopware6Service):
    search_path = "/search/order"

    def _build_open_order_criteria(
        self,
        *,
        sales_channel_id: str,
        page: int = 1,
        limit: int = 100,
    ) -> Criteria:
        criteria = Criteria(page=page, limit=limit, total_count_mode=1)

        criteria.associations["orderCustomer"] = Criteria()
        criteria.associations["orderCustomer"].associations["customer"] = Criteria()
        criteria.associations["orderCustomer"].associations["customer"].associations["group"] = Criteria()

        criteria.associations["billingAddress"] = Criteria()
        criteria.associations["billingAddress"].associations["country"] = Criteria()
        criteria.associations["billingAddress"].associations["salutation"] = Criteria()

        criteria.associations["deliveries"] = Criteria()
        criteria.associations["deliveries"].associations["shippingMethod"] = Criteria()
        criteria.associations["deliveries"].associations["shippingOrderAddress"] = Criteria()
        criteria.associations["deliveries"].associations["shippingOrderAddress"].associations["country"] = Criteria()

        criteria.associations["transactions"] = Criteria()
        criteria.associations["transactions"].associations["paymentMethod"] = Criteria()
        criteria.associations["stateMachineState"] = Criteria()
        criteria.associations["lineItems"] = Criteria()

        criteria.filter.append(EqualsFilter(field="salesChannelId", value=sales_channel_id))
        criteria.filter.append(EqualsFilter(field="stateMachineState.technicalName", value="open"))
        return criteria

    def list_open_by_sales_channel(
        self,
        *,
        sales_channel_id: str,
        page: int = 1,
        limit: int = 100,
    ) -> dict[str, Any]:
        payload = self._build_open_order_criteria(
            sales_channel_id=sales_channel_id,
            page=page,
            limit=limit,
        )
        return self.request_post(self.search_path, payload=payload)

    def list_all_open_by_sales_channel(
        self,
        *,
        sales_channel_id: str,
        limit_per_page: int = 100,
    ) -> dict[str, Any]:
        all_rows: list[dict[str, Any]] = []
        page = 1
        total = 0

        while True:
            response = self.list_open_by_sales_channel(
                sales_channel_id=sales_channel_id,
                page=page,
                limit=limit_per_page,
            )
            rows = (response or {}).get("data", []) or []
            total = int((response or {}).get("total") or total or 0)
            all_rows.extend(rows)

            if not rows:
                break
            if total and len(all_rows) >= total:
                break
            if len(rows) < limit_per_page:
                break

            page += 1

        return {
            "total": total or len(all_rows),
            "data": all_rows,
        }

    def get_by_id(self, order_id: str) -> dict[str, Any]:
        order_id = _to_str(order_id)
        if not order_id:
            raise ValueError("order_id is required.")

        criteria = Criteria(limit=1)
        criteria.associations["deliveries"] = Criteria()
        criteria.associations["deliveries"].associations["stateMachineState"] = Criteria()
        criteria.associations["transactions"] = Criteria()
        criteria.associations["transactions"].associations["stateMachineState"] = Criteria()
        criteria.associations["stateMachineState"] = Criteria()
        criteria.filter.append(EqualsFilter(field="id", value=order_id))
        return self.request_post(self.search_path, payload=criteria)

    def set_order_state(self, order_id: str, action_name: str) -> Any:
        order_id = _to_str(order_id)
        action_name = _to_str(action_name)
        if not order_id or not action_name:
            raise ValueError("order_id and action_name are required.")
        return self.request_post(f"/_action/order/{order_id}/state/{action_name}")

    def set_delivery_state(self, delivery_id: str, action_name: str) -> Any:
        delivery_id = _to_str(delivery_id)
        action_name = _to_str(action_name)
        if not delivery_id or not action_name:
            raise ValueError("delivery_id and action_name are required.")
        return self.request_post(f"/_action/order_delivery/{delivery_id}/state/{action_name}")

    def set_transaction_state(self, transaction_id: str, action_name: str) -> Any:
        transaction_id = _to_str(transaction_id)
        action_name = _to_str(action_name)
        if not transaction_id or not action_name:
            raise ValueError("transaction_id and action_name are required.")
        return self.request_post(f"/_action/order_transaction/{transaction_id}/state/{action_name}")

    def get_available_transition_actions(self, *, scope: str, entity_id: str) -> list[dict[str, str]]:
        scope = _to_str(scope).lower()
        entity_id = _to_str(entity_id)
        if scope not in {"order", "delivery", "payment"}:
            raise ValueError("scope must be one of: order, delivery, payment.")
        if not entity_id:
            return []

        endpoints = self._transition_endpoints(scope=scope, entity_id=entity_id)
        for endpoint in endpoints:
            for method in (self.request_get, self.request_post):
                try:
                    response = method(endpoint)
                except Exception as exc:  # pragma: no cover - remote runtime behavior
                    logger.debug(
                        "Could not fetch transition actions via {} {}: {}",
                        method.__name__,
                        endpoint,
                        exc,
                    )
                    continue

                actions = self._extract_transition_actions(response)
                if actions:
                    return actions

        fallback = DEFAULT_TRANSITION_ACTIONS.get(scope, [])
        return [{"action": value, "label": value.replace("_", " ")} for value in fallback]

    @staticmethod
    def _transition_endpoints(*, scope: str, entity_id: str) -> list[str]:
        if scope == "order":
            return [
                f"/_action/order/{entity_id}/state",
                f"/_action/state-machine/order/{entity_id}/state",
            ]
        if scope == "delivery":
            return [
                f"/_action/order_delivery/{entity_id}/state",
                f"/_action/state-machine/order_delivery/{entity_id}/state",
            ]
        return [
            f"/_action/order_transaction/{entity_id}/state",
            f"/_action/state-machine/order_transaction/{entity_id}/state",
        ]

    @staticmethod
    def _extract_transition_actions(payload: Any) -> list[dict[str, str]]:
        if payload is None:
            return []

        candidates: list[Any]
        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            raw = payload.get("data")
            if isinstance(raw, list):
                candidates = raw
            elif isinstance(raw, dict):
                candidates = list(raw.values())
            elif isinstance(payload.get("transitions"), list):
                candidates = payload["transitions"]
            elif isinstance(payload.get("actions"), list):
                candidates = payload["actions"]
            else:
                candidates = list(payload.values())
        else:
            return []

        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue

            action = _to_str(
                item.get("actionName")
                or item.get("action_name")
                or item.get("action")
                or item.get("technicalName")
                or item.get("name")
            )
            if not action or action in seen:
                continue

            label = _to_str(
                item.get("name")
                or item.get("label")
                or item.get("technicalName")
                or item.get("actionName")
                or action
            )
            result.append({"action": action, "label": label})
            seen.add(action)

        return result


__all__ = ["OrderService", "DEFAULT_TRANSITION_ACTIONS"]
