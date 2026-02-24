from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.services import BaseService
from customer.models import Address, Customer
from loguru import logger
from microtech.services import (
    MicrotechAdresseService,
    MicrotechAnschriftService,
    MicrotechAnsprechpartnerService,
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

    def upsert_customer(self, customer: Customer) -> UpsertResult:
        if not isinstance(customer, Customer):
            raise TypeError("customer must be an instance of Customer.")

        shipping = customer.shipping_address or customer.addresses.first()
        if not shipping:
            raise ValueError("Customer has no address to sync.")

        billing = customer.billing_address or shipping

        with microtech_connection() as erp:
            adresse_service = MicrotechAdresseService(erp=erp)
            anschrift_service = MicrotechAnschriftService(erp=erp)
            ansprechpartner_service = MicrotechAnsprechpartnerService(erp=erp)

            erp_nr, is_new_customer = self._upsert_adresse_record(
                customer=customer,
                shipping=shipping,
                adresse_service=adresse_service,
            )

            if not erp_nr:
                raise ValueError("Could not determine ERP number after address upsert.")

            shipping_ans_nr, billing_ans_nr = self._upsert_anschriften_and_contacts(
                customer=customer,
                erp_nr=erp_nr,
                shipping=shipping,
                billing=billing,
                anschrift_service=anschrift_service,
                ansprechpartner_service=ansprechpartner_service,
            )

            # Save default address numbers on top-level address record.
            adresse_service.edit()
            adresse_service.set_field("LiAnsNr", shipping_ans_nr)
            adresse_service.set_field("ReAnsNr", billing_ans_nr)
            adresse_service.post()

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

    def _upsert_adresse_record(
        self,
        *,
        customer: Customer,
        shipping: Address,
        adresse_service: MicrotechAdresseService,
    ) -> tuple[str, bool]:
        existing_erp_nr = _to_str(customer.erp_nr)
        exists_in_erp = bool(existing_erp_nr and adresse_service.find(existing_erp_nr))
        is_new_customer = not exists_in_erp

        if exists_in_erp:
            adresse_service.edit()
            erp_nr = existing_erp_nr
        else:
            adresse_service.append()
            next_nr = adresse_service.get_next_nr()
            if next_nr is None:
                raise ValueError("Microtech did not return a new AdrNr.")
            erp_nr = _to_str(next_nr)
            adresse_service.set_field("AdrNr", erp_nr)

        adresse_service.set_field("Status", "GC-SW6 Webshop Kunde")
        if customer.vat_id:
            adresse_service.set_field("UStIdNr", customer.vat_id)
        adresse_service.set_field("UStKat", self._resolve_ustkat(shipping.country_code, customer.vat_id))
        adresse_service.post()

        if customer.erp_nr != erp_nr:
            customer.erp_nr = erp_nr
            customer.save(update_fields=["erp_nr", "updated_at"])

        return erp_nr, is_new_customer

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

    def _upsert_anschriften_and_contacts(
        self,
        *,
        customer: Customer,
        erp_nr: str,
        shipping: Address,
        billing: Address,
        anschrift_service: MicrotechAnschriftService,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> tuple[int, int]:
        self._reset_anschrift_standard_flags(erp_nr=erp_nr, anschrift_service=anschrift_service)

        shipping_ans_nr = self._determine_ans_nr(
            erp_nr=erp_nr,
            address=shipping,
            anschrift_service=anschrift_service,
        )
        billing_ans_nr = shipping_ans_nr if billing.pk == shipping.pk else self._determine_ans_nr(
            erp_nr=erp_nr,
            address=billing,
            anschrift_service=anschrift_service,
            reserved={shipping_ans_nr},
        )

        self._upsert_anschrift_and_contact(
            erp_nr=erp_nr,
            address=shipping,
            ans_nr=shipping_ans_nr,
            is_shipping=True,
            is_invoice=billing.pk == shipping.pk,
            anschrift_service=anschrift_service,
            ansprechpartner_service=ansprechpartner_service,
        )

        if billing.pk != shipping.pk:
            self._upsert_anschrift_and_contact(
                erp_nr=erp_nr,
                address=billing,
                ans_nr=billing_ans_nr,
                is_shipping=False,
                is_invoice=True,
                anschrift_service=anschrift_service,
                ansprechpartner_service=ansprechpartner_service,
            )

        return shipping_ans_nr, billing_ans_nr

    def _reset_anschrift_standard_flags(
        self,
        *,
        erp_nr: str,
        anschrift_service: MicrotechAnschriftService,
    ) -> None:
        if not anschrift_service.set_range(from_range=[erp_nr, 0], to_range=[erp_nr, 999]):
            return
        while not anschrift_service.range_eof():
            anschrift_service.edit()
            anschrift_service.set_field("StdLiKz", False)
            anschrift_service.set_field("StdReKz", False)
            anschrift_service.post()
            anschrift_service.range_next()

    def _determine_ans_nr(
        self,
        *,
        erp_nr: str,
        address: Address,
        anschrift_service: MicrotechAnschriftService,
        reserved: set[int] | None = None,
    ) -> int:
        reserved = reserved or set()
        _, resolved_ans_nr = self._hydrate_anschrift_index_from_erp(
            erp_nr=erp_nr,
            address=address,
            anschrift_service=anschrift_service,
        )

        if resolved_ans_nr and resolved_ans_nr not in reserved:
            return resolved_ans_nr

        # Compute next free AnsNr.
        highest = 0
        if anschrift_service.set_range(from_range=[erp_nr, 0], to_range=[erp_nr, 999]):
            anschrift_service.range_last()
            highest = _to_int(anschrift_service.get_field("AnsNr")) or 0

        candidate = max(1, highest + 1)
        while candidate in reserved:
            candidate += 1
        return candidate

    def _upsert_anschrift_and_contact(
        self,
        *,
        erp_nr: str,
        address: Address,
        ans_nr: int,
        is_shipping: bool,
        is_invoice: bool,
        anschrift_service: MicrotechAnschriftService,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> None:
        self._hydrate_anschrift_index_from_erp(
            erp_nr=erp_nr,
            address=address,
            anschrift_service=anschrift_service,
        )
        found = False

        if address.erp_ans_id and anschrift_service.find(address.erp_ans_id, index_field="ID"):
            found = True
        elif anschrift_service.find([erp_nr, ans_nr]):
            found = True

        if found:
            anschrift_service.edit()
        else:
            anschrift_service.append()
            anschrift_service.set_field("AnsNr", ans_nr)

        self._map_anschrift_fields(
            erp_nr=erp_nr,
            address=address,
            is_shipping=is_shipping,
            is_invoice=is_invoice,
            anschrift_service=anschrift_service,
        )
        anschrift_service.post()

        self._persist_anschrift_identity(
            erp_nr=erp_nr,
            address=address,
            ans_id=_to_int(anschrift_service.get_field("ID")),
            ans_nr=_to_int(anschrift_service.get_field("AnsNr")) or ans_nr,
        )

        self._upsert_ansprechpartner(
            erp_nr=erp_nr,
            ans_nr=_to_int(address.erp_ans_nr) or ans_nr,
            address=address,
            ansprechpartner_service=ansprechpartner_service,
        )

    def _hydrate_anschrift_index_from_erp(
        self,
        *,
        erp_nr: str,
        address: Address,
        anschrift_service: MicrotechAnschriftService,
    ) -> tuple[int | None, int | None]:
        if address.erp_ans_id and anschrift_service.find(address.erp_ans_id, index_field="ID"):
            resolved_ans_id = _to_int(anschrift_service.get_field("ID")) or _to_int(address.erp_ans_id)
            resolved_ans_nr = _to_int(anschrift_service.get_field("AnsNr"))
            self._persist_anschrift_identity(
                erp_nr=erp_nr,
                address=address,
                ans_id=resolved_ans_id,
                ans_nr=resolved_ans_nr,
            )
            return resolved_ans_id, resolved_ans_nr

        known_ans_nr = _to_int(address.erp_ans_nr)
        if known_ans_nr and anschrift_service.find([erp_nr, known_ans_nr]):
            resolved_ans_id = _to_int(anschrift_service.get_field("ID"))
            resolved_ans_nr = _to_int(anschrift_service.get_field("AnsNr")) or known_ans_nr
            self._persist_anschrift_identity(
                erp_nr=erp_nr,
                address=address,
                ans_id=resolved_ans_id,
                ans_nr=resolved_ans_nr,
            )
            return resolved_ans_id, resolved_ans_nr

        return _to_int(address.erp_ans_id), known_ans_nr

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

    def _map_anschrift_fields(
        self,
        *,
        erp_nr: str,
        address: Address,
        is_shipping: bool,
        is_invoice: bool,
        anschrift_service: MicrotechAnschriftService,
    ) -> None:
        land_numeric = _country_numeric(address.country_code)

        anschrift_service.set_field("AdrNr", erp_nr)
        anschrift_service.set_field("Na1", address.title or address.name1)
        anschrift_service.set_field("Na2", address.name1 or address.name2)
        anschrift_service.set_field("Na3", address.name2 or address.name3)
        anschrift_service.set_field("Str", address.street)
        anschrift_service.set_field("PLZ", address.postal_code)
        anschrift_service.set_field("Ort", address.city)
        anschrift_service.set_field("EMail1", address.email)
        anschrift_service.set_field("Tel", address.phone)
        anschrift_service.set_field("Abt", address.department)
        if land_numeric is not None:
            anschrift_service.set_field("Land", land_numeric)
        anschrift_service.set_field("StdLiKz", bool(is_shipping))
        anschrift_service.set_field("StdReKz", bool(is_invoice))

    def _upsert_ansprechpartner(
        self,
        *,
        erp_nr: str,
        ans_nr: int,
        address: Address,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> None:
        if not ans_nr:
            raise ValueError("ans_nr is required for Ansprechpartner upsert.")

        self._reset_ansprechpartner_standard_flags(
            erp_nr=erp_nr,
            ans_nr=ans_nr,
            ansprechpartner_service=ansprechpartner_service,
        )

        asp_nr = self._determine_asp_nr(
            erp_nr=erp_nr,
            ans_nr=ans_nr,
            address=address,
            ansprechpartner_service=ansprechpartner_service,
        )
        self._hydrate_ansprechpartner_index_from_erp(
            erp_nr=erp_nr,
            ans_nr=ans_nr,
            address=address,
            ansprechpartner_service=ansprechpartner_service,
        )

        found = False
        if address.erp_asp_id and ansprechpartner_service.find(address.erp_asp_id, index_field="ID"):
            found = True
        elif ansprechpartner_service.find([erp_nr, ans_nr, asp_nr]):
            found = True

        if found:
            ansprechpartner_service.edit()
        else:
            ansprechpartner_service.append()
            ansprechpartner_service.set_field("AspNr", asp_nr)

        self._map_ansprechpartner_fields(
            erp_nr=erp_nr,
            ans_nr=ans_nr,
            address=address,
            ansprechpartner_service=ansprechpartner_service,
        )
        ansprechpartner_service.set_field("StdKz", True)
        ansprechpartner_service.post()

        self._persist_ansprechpartner_identity(
            address=address,
            asp_id=_to_int(ansprechpartner_service.get_field("ID")),
            asp_nr=_to_int(ansprechpartner_service.get_field("AspNr")) or asp_nr,
        )

    def _reset_ansprechpartner_standard_flags(
        self,
        *,
        erp_nr: str,
        ans_nr: int,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> None:
        if not ansprechpartner_service.set_range(
            from_range=[erp_nr, ans_nr, 0],
            to_range=[erp_nr, ans_nr, 999],
        ):
            return
        while not ansprechpartner_service.range_eof():
            ansprechpartner_service.edit()
            ansprechpartner_service.set_field("StdKz", False)
            ansprechpartner_service.post()
            ansprechpartner_service.range_next()

    def _determine_asp_nr(
        self,
        *,
        erp_nr: str,
        ans_nr: int,
        address: Address,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> int:
        _, resolved_asp_nr = self._hydrate_ansprechpartner_index_from_erp(
            erp_nr=erp_nr,
            ans_nr=ans_nr,
            address=address,
            ansprechpartner_service=ansprechpartner_service,
        )
        if resolved_asp_nr:
            return resolved_asp_nr

        highest = 0
        if ansprechpartner_service.set_range(
            from_range=[erp_nr, ans_nr, 0],
            to_range=[erp_nr, ans_nr, 999],
        ):
            ansprechpartner_service.range_last()
            highest = _to_int(ansprechpartner_service.get_field("AspNr")) or 0

        return max(1, highest + 1)

    def _hydrate_ansprechpartner_index_from_erp(
        self,
        *,
        erp_nr: str,
        ans_nr: int,
        address: Address,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> tuple[int | None, int | None]:
        if address.erp_asp_id and ansprechpartner_service.find(address.erp_asp_id, index_field="ID"):
            resolved_asp_id = _to_int(ansprechpartner_service.get_field("ID")) or _to_int(address.erp_asp_id)
            resolved_asp_nr = _to_int(ansprechpartner_service.get_field("AspNr"))
            self._persist_ansprechpartner_identity(
                address=address,
                asp_id=resolved_asp_id,
                asp_nr=resolved_asp_nr,
            )
            return resolved_asp_id, resolved_asp_nr

        known_asp_nr = _to_int(address.erp_asp_nr)
        if known_asp_nr and ansprechpartner_service.find([erp_nr, ans_nr, known_asp_nr]):
            resolved_asp_id = _to_int(ansprechpartner_service.get_field("ID"))
            resolved_asp_nr = _to_int(ansprechpartner_service.get_field("AspNr")) or known_asp_nr
            self._persist_ansprechpartner_identity(
                address=address,
                asp_id=resolved_asp_id,
                asp_nr=resolved_asp_nr,
            )
            return resolved_asp_id, resolved_asp_nr

        return _to_int(address.erp_asp_id), known_asp_nr

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

    def _map_ansprechpartner_fields(
        self,
        *,
        erp_nr: str,
        ans_nr: int,
        address: Address,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
    ) -> None:
        first_name = address.first_name or ""
        last_name = address.last_name or ""
        if not first_name and not last_name:
            tokens = (address.name2 or address.name1).split(" ", 1)
            first_name = tokens[0] if tokens else ""
            last_name = tokens[1] if len(tokens) > 1 else ""

        ansprechpartner_service.set_field("AdrNr", erp_nr)
        ansprechpartner_service.set_field("AnsNr", ans_nr)
        ansprechpartner_service.set_field("Anr", address.title)
        ansprechpartner_service.set_field("VNa", first_name)
        ansprechpartner_service.set_field("NNa", last_name)
        ansprechpartner_service.set_field("AnspAufbau", 6)
        ansprechpartner_service.set_field("Ansp", f"{first_name} {last_name}".strip())
        ansprechpartner_service.set_field("EMail1", address.email)
        ansprechpartner_service.set_field("Tel1", address.phone)
        ansprechpartner_service.set_field("Abt", address.department)


__all__ = ["CustomerUpsertMicrotechService", "UpsertResult"]
