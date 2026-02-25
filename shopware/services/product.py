from __future__ import annotations

from typing import Any

from shopware.services.shopware6 import Shopware6Service


class ProductService(Shopware6Service):
    resource = "product"
    base_path = "/product"
    search_path = "/search/product"
    product_price_search_path = "/search/product-price"
    product_price_base_path = "/product-price"
    bulk_sync_path = "/_action/sync"

    def get(self, product_id: str) -> Any:
        return self.request_get(f"{self.base_path}/{product_id}")

    def list(self, criteria: dict | Any | None = None) -> Any:
        payload = self._criteria_payload(criteria)
        return self.request_post(self.search_path, payload=payload)

    def get_by_number(self, product_number: str, *, limit: int = 1) -> Any:
        criteria = {
            "filter": [
                {
                    "type": "equals",
                    "field": "productNumber",
                    "value": product_number,
                }
            ],
            "limit": limit,
        }
        return self.request_post(self.search_path, payload=criteria)

    def get_sku_map(self, product_numbers: list[str]) -> dict[str, str]:
        if not product_numbers:
            return {}
        criteria = {
            "filter": [
                {
                    "type": "equalsAny",
                    "field": "productNumber",
                    "value": "|".join(product_numbers),
                }
            ],
            "limit": len(product_numbers),
        }
        result = self.request_post(self.search_path, payload=criteria)
        mapping: dict[str, str] = {}
        for item in (result or {}).get("data", []):
            attrs = item.get("attributes") or {}
            product_number = attrs.get("productNumber")
            sku = item.get("id")
            if product_number and sku:
                mapping[product_number] = sku
        return mapping

    def bulk_upsert(self, payload: list[dict], *, entity_name: str = "product") -> Any:
        if not payload:
            return None
        sync_payload = {
            f"{entity_name}-bulk": {
                "entity": entity_name,
                "action": "upsert",
                "payload": payload,
            }
        }
        return self.request_post(self.bulk_sync_path, payload=sync_payload)

    def purge_product_prices_by_product_and_rule(self, *, product_ids: list[str], rule_ids: list[str]) -> int:
        product_ids = [str(value).strip() for value in (product_ids or []) if str(value).strip()]
        rule_ids = [str(value).strip() for value in (rule_ids or []) if str(value).strip()]
        if not product_ids or not rule_ids:
            return 0

        product_values = "|".join(sorted(set(product_ids)))
        rule_values = "|".join(sorted(set(rule_ids)))
        page = 1
        limit = 500
        price_ids: list[str] = []

        while True:
            payload = {
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "productId",
                        "value": product_values,
                    },
                    {
                        "type": "equalsAny",
                        "field": "ruleId",
                        "value": rule_values,
                    },
                ],
                "limit": limit,
                "page": page,
            }
            result = self.request_post(self.product_price_search_path, payload=payload)
            rows = (result or {}).get("data", []) or []
            if not rows:
                break

            for row in rows:
                row_id = self._entity_id(row)
                if row_id:
                    price_ids.append(row_id)

            if len(rows) < limit:
                break
            page += 1

        for price_id in sorted(set(price_ids)):
            self.request_delete(f"{self.product_price_base_path}/{price_id}")

        return len(set(price_ids))

    def create(self, payload: dict) -> Any:
        return self.request_post(self.base_path, payload=payload)

    def update(self, product_id: str, payload: dict) -> Any:
        return self.request_patch(f"{self.base_path}/{product_id}", payload=payload)

    def delete(self, product_id: str) -> Any:
        return self.request_delete(f"{self.base_path}/{product_id}")

    @staticmethod
    def _criteria_payload(criteria: dict | Any | None) -> dict:
        if criteria is None:
            return {}
        if isinstance(criteria, dict):
            return criteria
        if hasattr(criteria, "to_dict"):
            return criteria.to_dict()
        raise TypeError("criteria must be a dict or an object with to_dict().")

    @staticmethod
    def _entity_id(row: dict[str, Any]) -> str:
        if not isinstance(row, dict):
            return ""
        row_id = row.get("id")
        if row_id:
            return str(row_id).strip()
        attributes = row.get("attributes") or {}
        if isinstance(attributes, dict) and attributes.get("id"):
            return str(attributes["id"]).strip()
        return ""


__all__ = ["ProductService"]
