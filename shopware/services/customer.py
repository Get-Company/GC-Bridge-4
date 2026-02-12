from __future__ import annotations

from typing import Any

from .shopware6 import Criteria, EqualsFilter, Shopware6Service


class CustomerService(Shopware6Service):
    search_path = "/search/customer"

    def _base_customer_criteria(self, *, limit: int = 1) -> Criteria:
        criteria = Criteria(limit=limit)
        criteria.associations["salutation"] = Criteria()

        address_criteria = Criteria()
        address_criteria.associations["country"] = Criteria()
        address_criteria.associations["salutation"] = Criteria()
        criteria.associations["addresses"] = address_criteria
        return criteria

    def get_by_id(self, customer_id: str) -> dict[str, Any]:
        criteria = self._base_customer_criteria(limit=1)
        criteria.filter.append(EqualsFilter(field="id", value=customer_id))
        return self.request_post(self.search_path, payload=criteria)

    def get_by_customer_number(self, customer_number: str) -> dict[str, Any]:
        criteria = self._base_customer_criteria(limit=1)
        criteria.filter.append(EqualsFilter(field="customerNumber", value=customer_number))
        return self.request_post(self.search_path, payload=criteria)

    def update_customer(self, customer_id: str, payload: dict[str, Any]) -> Any:
        customer_id = str(customer_id).strip()
        if not customer_id:
            raise ValueError("customer_id is required.")
        return self.request_patch(f"/customer/{customer_id}", payload=payload)

    def update_customer_number(self, customer_id: str, customer_number: str) -> Any:
        customer_number = str(customer_number).strip()
        if not customer_number:
            raise ValueError("customer_number is required.")
        return self.update_customer(customer_id=customer_id, payload={"customerNumber": customer_number})


__all__ = ["CustomerService"]
