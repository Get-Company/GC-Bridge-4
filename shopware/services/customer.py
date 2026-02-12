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


__all__ = ["CustomerService"]
