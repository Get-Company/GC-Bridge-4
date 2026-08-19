from __future__ import annotations

from typing import Any

from .shopware6 import ContainsFilter, Criteria, EqualsFilter, Shopware6Service


class CustomerService(Shopware6Service):
    search_path = "/search/customer"

    def count_active_accounts(self) -> int:
        """Return the number of enabled customer accounts in Shopware 6."""
        response = self.request_post(
            self.search_path,
            payload={
                "filter": [
                    {
                        "type": "equals",
                        "field": "active",
                        "value": True,
                    }
                ],
                "limit": 1,
                "total-count-mode": 1,
            },
        )
        total = (response or {}).get("total")
        if total is None:
            raise RuntimeError("Shopware did not return an active-customer count.")
        try:
            return max(0, int(total))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Shopware returned an invalid active-customer count.") from exc

    def _base_customer_criteria(self, *, limit: int = 1) -> Criteria:
        criteria = Criteria(limit=limit)
        criteria.associations["salutation"] = Criteria()
        criteria.associations["group"] = Criteria()

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

    def search_by_name(self, name: str, *, limit: int = 20) -> dict[str, Any]:
        from lib_shopware6_api_base import MultiFilter
        criteria = self._base_customer_criteria(limit=limit)
        criteria.filter.append(MultiFilter(
            operator="OR",
            queries=[
                ContainsFilter(field="lastName", value=name),
                ContainsFilter(field="firstName", value=name),
                ContainsFilter(field="company", value=name),
            ],
        ))
        return self.request_post(self.search_path, payload=criteria)

    def get_by_email(
        self,
        *,
        email: str,
        sales_channel_id: str = "",
        limit: int = 1,
    ) -> dict[str, Any]:
        criteria = self._base_customer_criteria(limit=limit)
        criteria.filter.append(EqualsFilter(field="email", value=email))
        if sales_channel_id:
            criteria.filter.append(EqualsFilter(field="salesChannelId", value=sales_channel_id))
        return self.request_post(self.search_path, payload=criteria)

    def search_by_customer_fields(
        self,
        *,
        customer_number: str = "",
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search customers with the field-specific merge-search criteria."""
        criteria = self._base_customer_criteria(limit=limit)
        if customer_number:
            criteria.filter.append(EqualsFilter(field="customerNumber", value=customer_number))
        if email:
            criteria.filter.append(EqualsFilter(field="email", value=email))
        if first_name:
            criteria.filter.append(ContainsFilter(field="firstName", value=first_name))
        if last_name:
            criteria.filter.append(ContainsFilter(field="lastName", value=last_name))
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
