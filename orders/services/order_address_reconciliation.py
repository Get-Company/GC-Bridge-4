from __future__ import annotations

from typing import Any

from django.db import transaction

from core.services import BaseService
from customer.models import Address
from orders.models import Order


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


class OrderAddressReconciliationService(BaseService):
    """Manually link Shopware order addresses to existing Microtech records."""

    model = Order

    POSTAL_FIELDS = (
        ("postal:name1", "Firma / Name", "name1", "name1"),
        ("postal:name2", "Name Zusatz", "name2", "name2"),
        ("postal:name3", "Name Zusatz 2", "name3", "name3"),
        ("postal:department", "Abteilung", "department", "department"),
        ("postal:street", "Straße", "street", "street"),
        ("postal:postal_code", "PLZ", "postal_code", "zipCode"),
        ("postal:city", "Ort", "city", "city"),
        ("postal:country_code", "Land", "country_code", "country"),
        ("postal:email", "E-Mail", "email", "email"),
        ("postal:phone", "Telefon", "phone", "phone"),
    )
    CONTACT_FIELDS = (
        ("contact:title", "Anrede", "title", "salutation"),
        ("contact:first_name", "Vorname", "first_name", "firstName"),
        ("contact:last_name", "Nachname", "last_name", "lastName"),
        ("contact:department", "Abteilung", "department", "department"),
        ("contact:email", "E-Mail", "email", "email"),
        ("contact:phone", "Telefon", "phone", "phone"),
    )
    _FIELD_DEFINITIONS = POSTAL_FIELDS + CONTACT_FIELDS

    def get_comparison(self, *, order: Order, client: Any) -> dict[str, Any]:
        """Load the customer's existing Microtech addresses for the comparison UI."""
        customer = getattr(order, "customer", None)
        customer_number = _to_str(getattr(customer, "erp_nr", ""))
        if not customer_number:
            raise ValueError("Die Bestellung hat keinen Kunden mit AdrNr.")

        result = client.request_customer(customer_number)
        customer = self._customer_from_result(result)
        returned_number = _to_str(customer.get("customerNumber"))
        if not returned_number:
            raise ValueError(f"Kunde mit AdrNr {customer_number} wurde in Microtech nicht gefunden.")
        if _to_int(returned_number) != _to_int(customer_number):
            raise ValueError(f"Microtech lieferte AdrNr {returned_number} statt {customer_number}.")

        address_number = _to_int(customer.get("erpAddressNumber")) or _to_int(returned_number)
        if address_number is None:
            raise ValueError("Microtech lieferte keine numerische AdrNr.")

        candidates = [
            self._candidate_from_payload(payload, address_number=address_number)
            for payload in customer.get("addresses") or []
            if isinstance(payload, dict) and _to_int(payload.get("addressSubNumber")) is not None
        ]

        scopes = [self._scope_with_candidates(scope, candidates) for scope in self._address_scopes(order)]
        return {
            "customer_number": returned_number,
            "address_number": address_number,
            "scopes": scopes,
            "has_candidates": bool(candidates),
        }

    def apply_from_post_data(self, *, comparison: dict[str, Any], post_data: Any, client: Any) -> list[dict[str, Any]]:
        """Persist selected IDs and transfer only the explicitly selected values."""
        updates: list[dict[str, Any]] = []

        for scope in comparison["scopes"]:
            prefix = scope["key"]
            address_sub_number = _to_int(post_data.get(f"{prefix}_address_sub_number"))
            if address_sub_number is None:
                raise ValueError(f"Bitte wählen Sie eine Microtech-Anschrift für {scope['label']} aus.")

            candidate = next(
                (item for item in scope["candidates"] if item["address_sub_number"] == address_sub_number),
                None,
            )
            if candidate is None:
                raise ValueError("Die gewählte Microtech-Anschrift gehört nicht zu diesem Kunden.")

            selected_fields = set(post_data.getlist(f"{prefix}_fields"))
            known_fields = {definition[0] for definition in self._FIELD_DEFINITIONS}
            unknown_fields = selected_fields.difference(known_fields)
            if unknown_fields:
                raise ValueError("Die Auswahl enthält unbekannte Felder.")

            contact_number = self._selected_contact_number(
                value=post_data.get(f"{prefix}_contact_reference"),
                candidate=candidate,
            )
            postal_input = self._build_input(
                address=scope["address"],
                selected_fields=selected_fields,
                definitions=self.POSTAL_FIELDS,
            )
            contact_input = self._build_input(
                address=scope["address"],
                selected_fields=selected_fields,
                definitions=self.CONTACT_FIELDS,
            )
            if contact_input and contact_number is None:
                raise ValueError(f"Bitte wählen Sie einen Ansprechpartner für {scope['label']} aus.")

            if postal_input:
                client.update_postal_address(
                    comparison["address_number"],
                    address_sub_number,
                    postal_input,
                )
            if contact_input and contact_number is not None:
                client.update_contact_person(
                    comparison["address_number"],
                    address_sub_number,
                    contact_number,
                    contact_input,
                )

            updates.append(
                {
                    "address": scope["address"],
                    "address_number": comparison["address_number"],
                    "address_sub_number": address_sub_number,
                    "contact_number": contact_number,
                    "postal_fields": len(postal_input),
                    "contact_fields": len(contact_input),
                }
            )

        with transaction.atomic():
            for update in updates:
                self._persist_mapping(**update)

        return updates

    @classmethod
    def _address_scopes(cls, order: Order) -> list[dict[str, Any]]:
        shipping = getattr(order, "shipping_address", None)
        billing = getattr(order, "billing_address", None)
        if shipping is None and billing is None:
            raise ValueError("Die Bestellung hat keine Rechnungs- oder Lieferanschrift.")

        same_address = shipping is billing or (
            shipping is not None and billing is not None and shipping.pk and shipping.pk == billing.pk
        )
        if same_address:
            return [{"key": "shipping_billing", "label": "Liefer- und Rechnungsanschrift", "address": shipping}]

        scopes: list[dict[str, Any]] = []
        if shipping is not None:
            scopes.append({"key": "shipping", "label": "Lieferanschrift", "address": shipping})
        if billing is not None:
            scopes.append({"key": "billing", "label": "Rechnungsanschrift", "address": billing})
        return scopes

    @classmethod
    def _scope_with_candidates(cls, scope: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        address = scope["address"]
        selected_address_number = _to_int(address.erp_ans_nr)
        selected_contact_number = _to_int(address.erp_asp_nr)
        rendered_candidates = []

        for candidate in candidates:
            copied_candidate = {**candidate, "contacts": []}
            copied_candidate["is_selected"] = candidate["address_sub_number"] == selected_address_number
            for contact in candidate["contacts"]:
                copied_contact = {
                    **contact,
                    "is_selected": (
                        copied_candidate["is_selected"] and contact["contact_number"] == selected_contact_number
                    ),
                }
                copied_candidate["contacts"].append(copied_contact)
            rendered_candidates.append(copied_candidate)

        return {
            **scope,
            "field_values": cls._field_values(address),
            "candidates": rendered_candidates,
            "is_mapped": selected_address_number is not None,
            "is_contact_mapped": selected_contact_number is not None,
        }

    @classmethod
    def _field_values(cls, address: Address) -> list[dict[str, str]]:
        return [
            {"key": key, "label": label, "value": _to_str(getattr(address, source_field, ""))}
            for key, label, source_field, _remote_field in cls._FIELD_DEFINITIONS
        ]

    @staticmethod
    def _candidate_from_payload(payload: dict[str, Any], *, address_number: int) -> dict[str, Any]:
        address_sub_number = _to_int(payload.get("addressSubNumber"))
        assert address_sub_number is not None
        contacts = []
        for contact in payload.get("contacts") or []:
            if not isinstance(contact, dict):
                continue
            contact_number = _to_int(contact.get("contactNumber"))
            if contact_number is None:
                continue
            contact_name = " ".join(
                value
                for value in (
                    _to_str(contact.get("salutation")),
                    _to_str(contact.get("firstName")),
                    _to_str(contact.get("lastName")),
                )
                if value
            ) or _to_str(contact.get("displayName")) or "-"
            contacts.append(
                {
                    "contact_number": contact_number,
                    "label": contact_name,
                    "email": _to_str(contact.get("email")),
                }
            )

        name = " · ".join(
            value
            for value in (
                _to_str(payload.get("name1")),
                _to_str(payload.get("name2")),
                _to_str(payload.get("name3")),
            )
            if value
        ) or "-"
        location = " ".join(
            value for value in (_to_str(payload.get("zipCode")), _to_str(payload.get("city"))) if value
        )
        return {
            "address_number": _to_int(payload.get("addressNumber")) or address_number,
            "address_sub_number": address_sub_number,
            "name": name,
            "street": _to_str(payload.get("street")),
            "location": location,
            "country": _to_str(payload.get("country")),
            "is_default_shipping": bool(payload.get("isDefaultShipping")),
            "is_default_billing": bool(payload.get("isDefaultBilling")),
            "contacts": contacts,
        }

    @staticmethod
    def _customer_from_result(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        customer = payload.get("customer")
        if isinstance(customer, dict):
            return customer
        for value in payload.values():
            customer = OrderAddressReconciliationService._customer_from_result(value)
            if customer:
                return customer
        return {}

    @staticmethod
    def _selected_contact_number(*, value: Any, candidate: dict[str, Any]) -> int | None:
        reference = _to_str(value)
        if not reference:
            return None
        try:
            address_sub_number, contact_number = (int(item) for item in reference.split(":", 1))
        except (TypeError, ValueError):
            raise ValueError("Der ausgewählte Ansprechpartner ist ungültig.") from None

        if address_sub_number != candidate["address_sub_number"]:
            raise ValueError("Der Ansprechpartner gehört nicht zur gewählten Anschrift.")
        if not any(contact["contact_number"] == contact_number for contact in candidate["contacts"]):
            raise ValueError("Der ausgewählte Ansprechpartner existiert nicht mehr in Microtech.")
        return contact_number

    @staticmethod
    def _build_input(
        *,
        address: Address,
        selected_fields: set[str],
        definitions: tuple[tuple[str, str, str, str], ...],
    ) -> dict[str, str]:
        input_data = {}
        for key, _label, source_field, remote_field in definitions:
            value = _to_str(getattr(address, source_field, ""))
            if key in selected_fields and value:
                input_data[remote_field] = value
        return input_data

    @staticmethod
    def _persist_mapping(
        *,
        address: Address,
        address_number: int,
        address_sub_number: int,
        contact_number: int | None,
        **_kwargs: Any,
    ) -> None:
        update_fields: list[str] = []
        if address.erp_nr != address_number:
            address.erp_nr = address_number
            update_fields.append("erp_nr")
        if address.erp_ans_nr != address_sub_number:
            address.erp_ans_nr = address_sub_number
            update_fields.append("erp_ans_nr")
        if contact_number is not None and address.erp_asp_nr != contact_number:
            address.erp_asp_nr = contact_number
            update_fields.append("erp_asp_nr")
        if contact_number is not None and address.erp_asp_id != contact_number:
            address.erp_asp_id = contact_number
            update_fields.append("erp_asp_id")
        if update_fields:
            address.save(update_fields=(*update_fields, "updated_at"))


__all__ = ["OrderAddressReconciliationService"]
