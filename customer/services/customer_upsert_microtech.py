from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.services import BaseService
from customer.models import Address, Customer
from loguru import logger
from microtech.services import (
    GraphQLMicrotechError,
    MicrotechGraphQLClientService,
    microtech_connection,
)
from shopware.services import CustomerService


EU_COUNTRY_CODES = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}

# Normalized salutation values that map to german outputs for Na1.
_SALUTATION_FEMALE_VALUES = {
    "frau",
    "fr",
    "mrs",
    "ms",
    "miss",
    "madam",
    "madame",
    "weiblich",
    "female",
    "w",
    "f",
}
_SALUTATION_MALE_VALUES = {
    "herr",
    "hr",
    "mr",
    "mister",
    "mann",
    "male",
    "monsieur",
    "m",
    "h",
}

# ISO-3166 numeric (only commonly used values in this integration context)
ISO2_TO_NUMERIC = {
    "DE": 276,
    "AT": 40,
    "BE": 56,
    "BG": 100,
    "CH": 756,
    "CY": 196,
    "CZ": 203,
    "DK": 208,
    "EE": 233,
    "ES": 724,
    "FI": 246,
    "FR": 250,
    "GB": 826,
    "GR": 300,
    "HR": 191,
    "HU": 348,
    "IE": 372,
    "IT": 380,
    "LT": 440,
    "LU": 442,
    "LV": 428,
    "MT": 470,
    "NL": 528,
    "PL": 616,
    "PT": 620,
    "RO": 642,
    "SE": 752,
    "SI": 705,
    "SK": 703,
    "US": 840,
}


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _country_numeric(country_code: str) -> int | None:
    code = _to_str(country_code).upper()
    if not code:
        return None
    if code.isdigit():
        return int(code)
    return ISO2_TO_NUMERIC.get(code)


def _normalize_salutation(value: Any) -> str:
    text = _to_str(value).lower()
    if not text:
        return ""
    for char in (".", ",", ";", ":", "-", "_", "/", "\\", "(", ")", "[", "]", "{", "}"):
        text = text.replace(char, " ")
    return " ".join(text.split())


@dataclass(slots=True)
class UpsertResult:
    customer: Customer
    erp_nr: str
    shipping_ans_nr: int
    billing_ans_nr: int
    is_new_customer: bool = False
    shopware_updated: bool = False


class CustomerUpsertMicrotechService(BaseService):
    model = Customer

    def upsert_customer(
        self,
        customer: Customer,
        *,
        shipping_address: Address | None = None,
        billing_address: Address | None = None,
        na1_mode: str = "auto",
        na1_static_value: str = "",
        erp: Any | None = None,
    ) -> UpsertResult:
        if not isinstance(customer, Customer):
            raise TypeError("customer must be an instance of Customer.")

        if shipping_address and shipping_address.customer_id != customer.id:
            raise ValueError("shipping_address does not belong to the customer.")
        if billing_address and billing_address.customer_id != customer.id:
            raise ValueError("billing_address does not belong to the customer.")

        shipping = shipping_address or customer.shipping_address or customer.addresses.first()
        if not shipping:
            raise ValueError("Customer has no address to sync.")

        billing = billing_address or customer.billing_address or shipping

        if erp is None:
            with microtech_connection() as erp_connection:
                return self.upsert_customer(
                    customer,
                    shipping_address=shipping_address,
                    billing_address=billing_address,
                    na1_mode=na1_mode,
                    na1_static_value=na1_static_value,
                    erp=erp_connection,
                )

        if not isinstance(erp, MicrotechGraphQLClientService):
            raise TypeError("Microtech upsert requires MicrotechGraphQLClientService.")
        return self._upsert_customer_graphql(
            customer=customer,
            shipping=shipping,
            billing=billing,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
            client=erp,
        )

    def _upsert_customer_graphql(
        self,
        *,
        customer: Customer,
        shipping: Address,
        billing: Address,
        na1_mode: str,
        na1_static_value: str,
        client: MicrotechGraphQLClientService,
    ) -> UpsertResult:
        erp_nr = _to_str(customer.erp_nr)
        if not erp_nr:
            raise ValueError(
                "Customer.erp_nr is required for GraphQL Microtech upsert until the wrapper exposes number allocation."
            )

        input_data = self._build_customer_input(customer=customer, address=shipping)
        is_new_customer = False
        try:
            client.request_customer(erp_nr)
            client.update_customer(erp_nr, input_data)
        except GraphQLMicrotechError:
            is_new_customer = True
            client.create_customer(erp_nr, input_data)

        address_number = _to_int(erp_nr)
        if address_number is None:
            raise ValueError(f"Customer.erp_nr '{erp_nr}' is not a numeric Microtech address number.")

        shipping_ans_nr = self._upsert_postal_address_graphql(
            client=client,
            address_number=address_number,
            address=shipping,
            is_shipping=True,
            is_invoice=billing.pk == shipping.pk,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
        )
        billing_ans_nr = shipping_ans_nr
        if billing.pk != shipping.pk:
            billing_ans_nr = self._upsert_postal_address_graphql(
                client=client,
                address_number=address_number,
                address=billing,
                is_shipping=False,
                is_invoice=True,
                na1_mode=na1_mode,
                na1_static_value=na1_static_value,
            )

        client.update_customer(
            erp_nr,
            {
                "defaultShippingAddressNumber": shipping_ans_nr,
                "defaultBillingAddressNumber": billing_ans_nr,
            },
        )

        shopware_updated = False
        if is_new_customer:
            shopware_updated = self._sync_new_customer_number_to_shopware(customer=customer, erp_nr=erp_nr)

        return UpsertResult(
            customer=customer,
            erp_nr=erp_nr,
            shipping_ans_nr=shipping_ans_nr,
            billing_ans_nr=billing_ans_nr,
            is_new_customer=is_new_customer,
            shopware_updated=shopware_updated,
        )

    def _upsert_postal_address_graphql(
        self,
        *,
        client: MicrotechGraphQLClientService,
        address_number: int,
        address: Address,
        is_shipping: bool,
        is_invoice: bool,
        na1_mode: str,
        na1_static_value: str,
    ) -> int:
        input_data = self._build_postal_address_input(
            address=address,
            is_shipping=is_shipping,
            is_invoice=is_invoice,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
        )
        address_sub_number = _to_int(address.erp_ans_nr)
        if address_sub_number:
            result = client.update_postal_address(address_number, address_sub_number, input_data)
        else:
            result = client.create_postal_address(address_number, input_data)

        postal_address = result.get("postalAddress") or {}
        resolved_sub_number = _to_int(postal_address.get("addressSubNumber")) or address_sub_number or 1
        self._persist_anschrift_identity(
            erp_nr=str(address_number),
            address=address,
            ans_id=_to_int(postal_address.get("addressNumber")) or address.erp_ans_id,
            ans_nr=resolved_sub_number,
        )
        self._upsert_contact_person_graphql(
            client=client,
            address_number=address_number,
            address_sub_number=resolved_sub_number,
            address=address,
        )
        return resolved_sub_number

    def _upsert_contact_person_graphql(
        self,
        *,
        client: MicrotechGraphQLClientService,
        address_number: int,
        address_sub_number: int,
        address: Address,
    ) -> None:
        input_data = self._build_contact_person_input(address=address)
        contact_number = _to_int(address.erp_asp_nr)
        if contact_number:
            result = client.update_contact_person(address_number, address_sub_number, contact_number, input_data)
        else:
            result = client.create_contact_person(address_number, address_sub_number, input_data)
        contact = result.get("contactPerson") or {}
        self._persist_ansprechpartner_identity(
            address=address,
            asp_id=_to_int(contact.get("contactNumber")) or address.erp_asp_id,
            asp_nr=_to_int(contact.get("contactNumber")) or contact_number,
        )

    def _build_customer_input(self, *, customer: Customer, address: Address) -> dict[str, Any]:
        return self._drop_blank(
            {
                "salutation": self._translate_salutation_to_de(address.title or address.name1),
                "firstName": address.first_name,
                "lastName": address.last_name,
                "name1": address.name1 or customer.name,
                "name2": address.name2,
                "name3": address.name3,
                "street": address.street,
                "zipCode": address.postal_code,
                "city": address.city,
                "email": address.email or customer.email,
                "phone": address.phone,
                "department": address.department,
                "country": address.country_code,
            }
        )

    def _build_postal_address_input(
        self,
        *,
        address: Address,
        is_shipping: bool,
        is_invoice: bool,
        na1_mode: str,
        na1_static_value: str,
    ) -> dict[str, Any]:
        return self._drop_blank(
            {
                "isDefaultShipping": bool(is_shipping),
                "isDefaultBilling": bool(is_invoice),
                "name1": self._resolve_na1_for_anschrift(
                    address=address,
                    na1_mode=na1_mode,
                    na1_static_value=na1_static_value,
                ) or address.name1,
                "name2": address.name2,
                "name3": address.name3,
                "street": address.street,
                "zipCode": address.postal_code,
                "city": address.city,
                "email": address.email,
                "phone": address.phone,
                "department": address.department,
                "country": address.country_code,
            }
        )

    def _build_contact_person_input(self, *, address: Address) -> dict[str, Any]:
        first_name = address.first_name or ""
        last_name = address.last_name or ""
        if not first_name and not last_name:
            tokens = (address.name2 or address.name1).split(" ", 1)
            first_name = tokens[0] if tokens else ""
            last_name = tokens[1] if len(tokens) > 1 else ""
        return self._drop_blank(
            {
                "isDefault": True,
                "salutation": address.title,
                "firstName": first_name,
                "lastName": last_name,
                "displayName": f"{first_name} {last_name}".strip(),
                "department": address.department,
                "email": address.email,
                "phone": address.phone,
            }
        )

    @staticmethod
    def _drop_blank(data: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in data.items() if value not in (None, "")}

    def _sync_new_customer_number_to_shopware(self, *, customer: Customer, erp_nr: str) -> bool:
        customer_id = _to_str(customer.api_id)
        if not customer_id:
            logger.warning(
                "Shopware customer update skipped for ERP {}: missing customer.api_id (customer_id={}).",
                erp_nr,
                customer.id,
            )
            return False

        service = CustomerService()
        existing = service.get_by_customer_number(erp_nr)
        existing_data = (existing or {}).get("data", []) or []

        for item in existing_data:
            item_id = _to_str((item or {}).get("id"))
            if not item_id:
                item_id = _to_str(((item or {}).get("attributes") or {}).get("id"))
            if item_id and item_id != customer_id:
                raise ValueError(
                    f"Shopware customerNumber '{erp_nr}' is already used by customer '{item_id}'."
                )

        service.update_customer_number(customer_id=customer_id, customer_number=erp_nr)
        logger.info(
            "Shopware customer {} updated with new customerNumber {} (local customer_id={}).",
            customer_id,
            erp_nr,
            customer.id,
        )
        return True

    @staticmethod
    def _resolve_ustkat(country_code: str, vat_id: str) -> int:
        code = _to_str(country_code).upper()
        has_vat_id = bool(_to_str(vat_id))

        if code == "DE":
            return 1
        if code == "CH":
            return 2
        if code in EU_COUNTRY_CODES:
            return 3 if has_vat_id else 1
        return 3

    def _persist_anschrift_identity(
        self,
        *,
        erp_nr: str,
        address: Address,
        ans_id: int | None,
        ans_nr: int | None,
    ) -> None:
        update_fields: list[str] = []
        erp_nr_int = _to_int(erp_nr)
        if erp_nr_int is not None and address.erp_nr != erp_nr_int:
            address.erp_nr = erp_nr_int
            update_fields.append("erp_nr")
        if ans_id is not None and address.erp_ans_id != ans_id:
            address.erp_ans_id = ans_id
            update_fields.append("erp_ans_id")
        if ans_nr is not None and address.erp_ans_nr != ans_nr:
            address.erp_ans_nr = ans_nr
            update_fields.append("erp_ans_nr")
        if update_fields:
            address.save(update_fields=[*update_fields, "updated_at"])

    @staticmethod
    def _translate_salutation_to_de(value: Any) -> str:
        normalized = _normalize_salutation(value)
        if not normalized:
            return ""
        if normalized in _SALUTATION_FEMALE_VALUES:
            return "Frau"
        if normalized in _SALUTATION_MALE_VALUES:
            return "Herr"
        return ""

    @staticmethod
    def _looks_like_company(*, address: Address) -> bool:
        company_candidate = _to_str(address.name1)
        if not company_candidate:
            return False
        if _to_str(address.name2) and _to_str(address.name2) == company_candidate:
            return True
        if _to_str(address.first_name) or _to_str(address.last_name):
            return False
        return True

    def _resolve_na1_for_anschrift(
        self,
        *,
        address: Address,
        na1_mode: str = "auto",
        na1_static_value: str = "",
    ) -> str:
        company_candidate = _to_str(address.name1)
        is_company = bool(
            self._looks_like_company(address=address)
            and not self._translate_salutation_to_de(company_candidate)
        )
        mode = _to_str(na1_mode).lower() or "auto"
        translated_salutation = self._translate_salutation_to_de(address.title or address.name1)

        if mode == "static":
            return _to_str(na1_static_value) or _to_str(address.title) or company_candidate
        if mode == "salutation_only":
            return translated_salutation or _to_str(address.title) or company_candidate
        if mode == "firma_or_salutation":
            if is_company:
                return "Firma"
            return translated_salutation or _to_str(address.title) or company_candidate

        if is_company:
            return company_candidate

        if translated_salutation:
            return translated_salutation
        return _to_str(address.title) or company_candidate

    def _persist_ansprechpartner_identity(
        self,
        *,
        address: Address,
        asp_id: int | None,
        asp_nr: int | None,
    ) -> None:
        update_fields: list[str] = []
        if asp_id is not None and address.erp_asp_id != asp_id:
            address.erp_asp_id = asp_id
            update_fields.append("erp_asp_id")
        if asp_nr is not None and address.erp_asp_nr != asp_nr:
            address.erp_asp_nr = asp_nr
            update_fields.append("erp_asp_nr")
        if update_fields:
            address.save(update_fields=[*update_fields, "updated_at"])


__all__ = ["CustomerUpsertMicrotechService", "UpsertResult"]
