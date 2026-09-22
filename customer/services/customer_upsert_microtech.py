from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.services import BaseService
from customer.models import Address, Customer
from customer.services.webshop_mapping import CustomerWebshopMappingService
from loguru import logger
from microtech.services import (
    GraphQLMicrotechError,
    MicrotechGraphQLClientService,
    microtech_connection,
)
from shopware.services import CustomerService


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
NOT_FOUND_FRAGMENTS = ("nicht gefunden", "not found", "wurde nicht gefunden")


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


@dataclass(slots=True)
class UpsertResult:
    customer: Customer
    erp_nr: str
    shipping_ans_nr: int
    billing_ans_nr: int
    is_new_customer: bool = False
    shopware_updated: bool = False
    known_address_sub_numbers: set[int] | None = None


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
        input_overrides: Mapping[str, Any] | None = None,
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

        billing = billing_address or customer.billing_address
        if billing is None:
            raise ValueError(
                "Customer has no billing address to sync. Tax category must always be resolved from the billing address."
            )

        if erp is None:
            with microtech_connection() as erp_connection:
                return self.upsert_customer(
                    customer,
                    shipping_address=shipping_address,
                    billing_address=billing_address,
                    na1_mode=na1_mode,
                    na1_static_value=na1_static_value,
                    input_overrides=input_overrides,
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
            input_overrides=input_overrides,
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
        input_overrides: Mapping[str, Any] | None,
        client: MicrotechGraphQLClientService,
    ) -> UpsertResult:
        erp_nr = _to_str(customer.erp_nr)
        if not erp_nr:
            raise ValueError(
                "Customer.erp_nr is required for GraphQL Microtech upsert until the wrapper exposes number allocation."
            )

        # A scoped delivery/billing email rule cannot be fulfilled if both
        # roles collapse to one Microtech postal address.  Validate before the
        # customer master record is written so the upsert stays atomic from the
        # caller's perspective.
        from microtech.rule_engine.dispatch import ensure_customer_scope_email_targets_are_distinct_with_mode

        ensure_customer_scope_email_targets_are_distinct_with_mode(
            customer=customer,
            shipping_address=shipping,
            billing_address=billing,
            same_address=self._same_address(shipping, billing),
        )

        input_data = self._build_customer_input(
            customer=customer,
            address=shipping,
            billing_address=billing,
            input_overrides=input_overrides,
        )
        is_new_customer = False
        existing_customer: dict[str, Any] = {}
        try:
            result = client.request_customer(erp_nr)
            existing_customer = self._customer_from_result(result)
        except GraphQLMicrotechError as exc:
            if not self._looks_like_not_found_error(str(exc)):
                raise
            is_new_customer = True
            client.create_customer(erp_nr, input_data)
        else:
            if existing_customer.get("customerNumber"):
                client.update_customer(erp_nr, input_data)
            else:
                is_new_customer = True
                client.create_customer(erp_nr, input_data)

        address_number = _to_int(erp_nr)
        if address_number is None:
            raise ValueError(f"Customer.erp_nr '{erp_nr}' is not a numeric Microtech address number.")

        known_address_sub_numbers = (
            set() if is_new_customer else self._address_sub_numbers_from_customer(existing_customer)
        )
        shipping_ans_nr = self._upsert_postal_address_graphql(
            client=client,
            address_number=address_number,
            address=shipping,
            is_shipping=False,
            is_invoice=False,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
            known_address_sub_numbers=known_address_sub_numbers,
            include_email=True,
            customer=customer,
            shipping_address=shipping,
            billing_address=billing,
            target_scope="shipping_address",
        )
        billing_ans_nr = shipping_ans_nr
        if not self._same_address(shipping, billing):
            billing_ans_nr = self._upsert_postal_address_graphql(
                client=client,
                address_number=address_number,
                address=billing,
                is_shipping=False,
                is_invoice=False,
                na1_mode=na1_mode,
                na1_static_value=na1_static_value,
                known_address_sub_numbers=known_address_sub_numbers,
                include_email=False,
                customer=customer,
                shipping_address=shipping,
                billing_address=billing,
                target_scope="billing_address",
            )

        # A Vorgang is created with only the customer number.  Microtech then
        # resolves the contact from the address's default contact, so a manual
        # customer-merge assignment must replace any older default instead of
        # leaving the first contact active alongside the selected one.
        synced_contact_pairs = {
            (shipping_ans_nr, _to_int(shipping.erp_asp_nr)),
            (billing_ans_nr, _to_int(billing.erp_asp_nr)),
        }
        for address_sub_number, selected_contact_number in synced_contact_pairs:
            if selected_contact_number is None:
                continue
            self._clear_existing_default_contact_flags(
                client=client,
                address_number=address_number,
                customer=existing_customer,
                address_sub_number=address_sub_number,
                selected_contact_number=selected_contact_number,
            )

        self._clear_existing_default_flags(
            client=client,
            address_number=address_number,
            customer=existing_customer,
        )
        default_address_input = {
            "defaultShippingAddressNumber": shipping_ans_nr,
            "defaultBillingAddressNumber": billing_ans_nr,
        }
        # A partial CustomerInput update also writes ``UStKat`` in the wrapper.
        # Carry over the resolved category from the preceding customer upsert,
        # so setting address defaults cannot replace a rule value with a fallback.
        if "taxCategory" in input_data:
            default_address_input["taxCategory"] = input_data["taxCategory"]
        client.update_customer(erp_nr, default_address_input)

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
            known_address_sub_numbers=known_address_sub_numbers,
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
        known_address_sub_numbers: set[int] | None,
        include_email: bool,
        customer: Customer | None = None,
        shipping_address: Address | None = None,
        billing_address: Address | None = None,
        target_scope: str = "",
    ) -> int:
        input_data = self._build_postal_address_input(
            address=address,
            is_shipping=is_shipping,
            is_invoice=is_invoice,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
            include_email=include_email,
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            target_scope=target_scope,
        )
        address_sub_number = _to_int(address.erp_ans_nr)
        if address_sub_number is not None and (
            known_address_sub_numbers is None or address_sub_number in known_address_sub_numbers
        ):
            result = client.update_postal_address(address_number, address_sub_number, input_data)
        else:
            if address_sub_number is not None:
                logger.warning(
                    "Lokale AnsNr {} der Adresse {} ist nicht mehr in Microtech vorhanden; "
                    "neue Anschrift wird angelegt.",
                    address_sub_number,
                    address.pk,
                )
                self._clear_stale_address_identity(address)
            result = client.create_postal_address(address_number, input_data)

        postal_address = result.get("postalAddress") or {}
        resolved_sub_number = _to_int(postal_address.get("addressSubNumber"))
        if resolved_sub_number is None and address_sub_number is not None and known_address_sub_numbers is None:
            resolved_sub_number = address_sub_number
        if resolved_sub_number is None:
            raise ValueError("Microtech lieferte nach dem Anschriften-Upsert keine Anschrift-Nummer.")
        self._persist_anschrift_identity(
            erp_nr=str(address_number),
            address=address,
            # GraphQL's addressNumber is the customer AdrNr, not an Anschrift-ID.
            ans_id=address.erp_ans_id,
            ans_nr=resolved_sub_number,
        )
        if known_address_sub_numbers is not None:
            known_address_sub_numbers.add(resolved_sub_number)
        self._upsert_contact_person_graphql(
            client=client,
            address_number=address_number,
            address_sub_number=resolved_sub_number,
            address=address,
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            target_scope=(
                "shipping_contact" if target_scope == "shipping_address"
                else "billing_contact" if target_scope == "billing_address" else ""
            ),
        )
        return resolved_sub_number

    def _upsert_contact_person_graphql(
        self,
        *,
        client: MicrotechGraphQLClientService,
        address_number: int,
        address_sub_number: int,
        address: Address,
        customer: Customer | None = None,
        shipping_address: Address | None = None,
        billing_address: Address | None = None,
        target_scope: str = "",
    ) -> None:
        input_data = self._build_contact_person_input(
            address=address,
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            target_scope=target_scope,
        )
        contact_number = _to_int(address.erp_asp_nr)
        if contact_number is not None:
            result = client.update_contact_person(address_number, address_sub_number, contact_number, input_data)
        else:
            result = client.create_contact_person(address_number, address_sub_number, input_data)
        contact = result.get("contactPerson") or {}
        resolved_contact_number = _to_int(contact.get("contactNumber"))
        self._persist_ansprechpartner_identity(
            address=address,
            asp_id=resolved_contact_number if resolved_contact_number is not None else address.erp_asp_id,
            asp_nr=resolved_contact_number if resolved_contact_number is not None else contact_number,
        )

    def _build_customer_input(
        self,
        *,
        customer: Customer,
        address: Address,
        billing_address: Address | None = None,
        input_overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if billing_address is None:
            raise ValueError(
                "CustomerInput requires a billing address. Tax category must never fall back to the shipping address."
            )
        tax_address = billing_address
        customer_input = {
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
                "vatId": customer.vat_id,
                "taxCategory": CustomerWebshopMappingService.resolve_tax_category(
                    billing_country_code=tax_address.country_code,
                    vat_id=customer.vat_id,
                    customer_group=customer.shopware_customer_group,
                ),
                "webshopDefaults": CustomerWebshopMappingService().get_microtech_defaults(
                    country_code=address.country_code,
                ),
        }
        # Rule engine overlays CustomerInput fields (any of them at once) only in
        # live mode; off/shadow keep the hardcoded values above.
        from microtech.rule_engine.dispatch import resolve_customer_input_with_mode

        overlay = resolve_customer_input_with_mode(
            customer=customer, address=address, billing_address=billing_address,
            code_values=customer_input,
        )
        if overlay:
            customer_input.update(overlay)
        # An order rule runs with the concrete billing address of this order.
        # It therefore takes precedence over the general customer-write rules
        # above, which may be evaluated outside an order context.
        if input_overrides:
            customer_input.update(input_overrides)
        # Rule action values are rendered as text.  ``Adressen.UStKat`` is an
        # integer in Microtech, and GraphQL does not coerce JSON strings for an
        # ``Int`` input field.  Convert only this typed CustomerInput field
        # after all rules have been overlaid.
        if "taxCategory" in customer_input:
            customer_input["taxCategory"] = self._coerce_tax_category(
                customer_input["taxCategory"]
            )
        return self._drop_blank(customer_input)

    def _build_postal_address_input(
        self,
        *,
        address: Address,
        is_shipping: bool,
        is_invoice: bool,
        na1_mode: str,
        na1_static_value: str,
        include_email: bool | None = None,
        customer: Customer | None = None,
        shipping_address: Address | None = None,
        billing_address: Address | None = None,
        target_scope: str = "",
    ) -> dict[str, Any]:
        if include_email is None:
            include_email = is_shipping
        postal_mapping = CustomerWebshopMappingService().get_postal_address_mapping(address=address)
        code_na1 = self._resolve_na1_for_anschrift(
            address=address,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
        ) or postal_mapping["name1"]
        postal_input = {
                "isDefaultShipping": bool(is_shipping),
                "isDefaultBilling": bool(is_invoice),
                "name1": code_na1,
                "name2": postal_mapping["name2"],
                "name3": address.name3,
                "street": address.street,
                "zipCode": address.postal_code,
                "city": address.city,
                "email": address.email if include_email else None,
                "phone": address.phone,
                "department": address.department,
                "country": address.country_code,
        }
        # Rule engine overlays PostalAddressInput fields (any of them at once)
        # only in live mode; off/shadow keep the hardcoded values above.
        from microtech.rule_engine.dispatch import resolve_postal_address_with_mode

        overlay = resolve_postal_address_with_mode(address, code_values=postal_input)
        if overlay:
            # Invoice-address email is deliberately absent from the ordinary
            # customer upsert.  A generic address rule must not accidentally
            # reintroduce it; only an explicit billing-address scoped action
            # may choose to do so.
            if not include_email:
                overlay.pop("email", None)
            postal_input.update(overlay)
        if customer is not None and target_scope:
            from microtech.rule_engine.dispatch import resolve_customer_postal_address_with_mode

            scoped_overlay = resolve_customer_postal_address_with_mode(
                customer=customer,
                shipping_address=shipping_address,
                billing_address=billing_address,
                address=address,
                target_scope=target_scope,
                code_values=postal_input,
            )
            if scoped_overlay:
                postal_input.update(scoped_overlay)
        return self._drop_blank(postal_input)

    def _build_contact_person_input(
        self,
        *,
        address: Address,
        customer: Customer | None = None,
        shipping_address: Address | None = None,
        billing_address: Address | None = None,
        target_scope: str = "",
    ) -> dict[str, Any]:
        first_name = address.first_name or ""
        last_name = address.last_name or ""
        if not first_name and not last_name:
            tokens = (address.name2 or address.name1).split(" ", 1)
            first_name = tokens[0] if tokens else ""
            last_name = tokens[1] if len(tokens) > 1 else ""
        salutation = CustomerWebshopMappingService.get_contact_person_salutation(address=address)
        display_name = " ".join(part for part in (salutation, first_name, last_name) if part)
        contact_input = {
            "isDefault": True,
            "salutation": salutation,
            "firstName": first_name,
            "lastName": last_name,
            "displayName": display_name,
            "department": address.department,
            "email": address.email,
            "phone": address.phone,
        }
        if customer is not None and target_scope:
            from microtech.rule_engine.dispatch import resolve_customer_contact_person_with_mode

            scoped_overlay = resolve_customer_contact_person_with_mode(
                customer=customer,
                shipping_address=shipping_address,
                billing_address=billing_address,
                address=address,
                target_scope=target_scope,
                code_values=contact_input,
            )
            if scoped_overlay:
                contact_input.update(scoped_overlay)
        return self._drop_blank(contact_input)

    @staticmethod
    def _drop_blank(data: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in data.items() if value not in (None, "")}

    @staticmethod
    def _customer_from_result(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        customer = result.get("customer")
        if isinstance(customer, dict):
            return customer
        for value in result.values():
            customer = CustomerUpsertMicrotechService._customer_from_result(value)
            if customer:
                return customer
        return {}

    @staticmethod
    def _address_sub_numbers_from_customer(customer: dict[str, Any]) -> set[int] | None:
        addresses = customer.get("addresses") if isinstance(customer, dict) else None
        if not isinstance(addresses, list):
            return None
        return {
            sub_number
            for address in addresses
            if isinstance(address, dict)
            for sub_number in (_to_int(address.get("addressSubNumber")),)
            if sub_number is not None
        }

    @staticmethod
    def _same_address(shipping: Address, billing: Address) -> bool:
        """Keep one Microtech Anschrift for semantically identical addresses."""
        if shipping is billing or (shipping.pk and shipping.pk == billing.pk):
            return True
        fields = (
            "name1",
            "name2",
            "name3",
            "department",
            "street",
            "postal_code",
            "city",
            "country_code",
            "email",
            "phone",
            "title",
            "first_name",
            "last_name",
        )
        return all(
            str(getattr(shipping, field, "") or "").strip().casefold()
            == str(getattr(billing, field, "") or "").strip().casefold()
            for field in fields
        )

    @staticmethod
    def _looks_like_not_found_error(message: str) -> bool:
        lowered = str(message or "").lower()
        return any(fragment in lowered for fragment in NOT_FOUND_FRAGMENTS)

    def _clear_existing_default_flags(
        self,
        *,
        client: MicrotechGraphQLClientService,
        address_number: int,
        customer: dict[str, Any],
    ) -> None:
        """Clear every legacy default flag before assigning the final pair."""
        defaults = {
            "shipping": {_to_int(customer.get("defaultShippingAddressNumber"))},
            "billing": {_to_int(customer.get("defaultBillingAddressNumber"))},
        }
        for address in customer.get("addresses") or []:
            if not isinstance(address, dict):
                continue
            sub_number = _to_int(address.get("addressSubNumber"))
            if sub_number is None:
                continue
            if address.get("isDefaultShipping"):
                defaults["shipping"].add(sub_number)
            if address.get("isDefaultBilling"):
                defaults["billing"].add(sub_number)

        for role, numbers in defaults.items():
            field = "isDefaultShipping" if role == "shipping" else "isDefaultBilling"
            for sub_number in sorted(number for number in numbers if number is not None):
                client.update_postal_address(address_number, sub_number, {field: False})

    @staticmethod
    def _clear_existing_default_contact_flags(
        *,
        client: MicrotechGraphQLClientService,
        address_number: int,
        customer: dict[str, Any],
        address_sub_number: int,
        selected_contact_number: int | None,
    ) -> None:
        """Ensure a selected contact is the only default for its address."""
        for remote_address in customer.get("addresses") or []:
            if not isinstance(remote_address, dict):
                continue
            if _to_int(remote_address.get("addressSubNumber")) != address_sub_number:
                continue
            for contact in remote_address.get("contacts") or []:
                if not isinstance(contact, dict) or not contact.get("isDefault"):
                    continue
                contact_number = _to_int(contact.get("contactNumber"))
                if contact_number is None or contact_number == selected_contact_number:
                    continue
                client.update_contact_person(
                    address_number,
                    address_sub_number,
                    contact_number,
                    {"isDefault": False},
                )

    @staticmethod
    def _clear_stale_address_identity(address: Address) -> None:
        """Discard an Anschrift/contact mapping that Microtech no longer knows."""
        fields = ("erp_combined_id", "erp_ans_id", "erp_ans_nr", "erp_asp_id", "erp_asp_nr")
        update_fields = [field for field in fields if getattr(address, field) is not None]
        if not update_fields:
            return
        for field in update_fields:
            setattr(address, field, None)
        address.save(update_fields=(*update_fields, "updated_at"))

    def _sync_new_customer_number_to_shopware(self, *, customer: Customer, erp_nr: str) -> bool:
        erp_nr = _to_str(erp_nr)
        if not erp_nr:
            raise ValueError("Resolved Microtech customer number is required for Shopware write-back.")
        customer_id = _to_str(customer.api_id)
        if not customer_id:
            raise ValueError(
                "Shopware customer update requires customer.api_id "
                f"for resolved Microtech customer number {erp_nr} (customer_id={customer.id})."
            )

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
        if customer.erp_nr != erp_nr:
            customer.erp_nr = erp_nr
            customer.save(update_fields=("erp_nr", "updated_at"))
        logger.info(
            "Shopware customer {} updated with new customerNumber {} (local customer_id={}).",
            customer_id,
            erp_nr,
            customer.id,
        )
        return True

    @staticmethod
    def _resolve_ustkat(country_code: str, vat_id: str, customer_group: str = "") -> int:
        """Compatibility helper for callers that previously used this method."""
        return CustomerWebshopMappingService.resolve_tax_category(
            billing_country_code=country_code,
            vat_id=vat_id,
            customer_group=customer_group,
        )

    @staticmethod
    def _coerce_tax_category(value: Any) -> int:
        """Return a GraphQL-compatible integer for ``CustomerInput.taxCategory``."""
        if isinstance(value, bool):
            raise ValueError("CustomerInput.taxCategory must be an integer, not a boolean.")
        if isinstance(value, int):
            return value
        try:
            return int(_to_str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "CustomerInput.taxCategory must be configured as an integer value."
            ) from exc

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
        return CustomerWebshopMappingService.translate_salutation_to_de(value)

    @staticmethod
    def _looks_like_company(*, address: Address) -> bool:
        return CustomerWebshopMappingService.is_company_address(address=address)

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

        return CustomerWebshopMappingService().get_postal_address_mapping(address=address)["name1"]

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
