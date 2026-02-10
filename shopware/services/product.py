from __future__ import annotations

from typing import Any

from shopware.services.shopware6 import Shopware6Service


class ProductService(Shopware6Service):
    resource = "product"
    base_path = "/product"
    search_path = "/search/product"

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
