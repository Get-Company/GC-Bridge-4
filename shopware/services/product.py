from __future__ import annotations

from typing import Any

from shopware.services.shopware6 import Shopware6Service


class ProductService(Shopware6Service):
    resource = "product"
    base_path = "/product"
    search_path = "/search/product"
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


__all__ = ["ProductService"]
