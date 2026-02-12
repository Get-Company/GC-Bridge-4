from __future__ import annotations

from typing import Any

from .shopware6 import Criteria, EqualsFilter, Shopware6Service


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


__all__ = ["OrderService"]
