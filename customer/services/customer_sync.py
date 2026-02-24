from __future__ import annotations

from typing import Any

from loguru import logger

from core.services import BaseService
from customer.models import Address, Customer
from microtech.services import MicrotechAdresseService, microtech_connection
from microtech.services.anschrift import MicrotechAnschriftService
from microtech.services.ansprechpartner import MicrotechAnsprechpartnerService


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class CustomerSyncService(BaseService):
    model = Customer

    def sync_from_microtech(self, erp_nr: str) -> Customer:
        erp_nr = _to_str(erp_nr)
        if not erp_nr:
            raise ValueError("erp_nr is required.")

        with microtech_connection() as erp:
            address_service = MicrotechAdresseService(erp=erp)
            if not address_service.find(erp_nr):
                raise ValueError(f"Kunde mit AdrNr {erp_nr} nicht in Microtech gefunden.")

            customer_erp_nr = _to_str(address_service.get_field("AdrNr")) or erp_nr
            customer, _ = Customer.objects.get_or_create(erp_nr=customer_erp_nr)
            customer.name = _to_str(address_service.get_field("Na1"))
            customer.email = _to_str(address_service.get_field("EMail1"))
            customer.erp_id = _to_int(address_service.get_field("AdrId"))
            customer.save()

            standard_invoice_nr = _to_int(address_service.get_field("ReAnsNr"))
            standard_shipping_nr = _to_int(address_service.get_field("LiAnsNr"))

            anschrift_service = MicrotechAnschriftService(erp=erp)
            ansprechpartner_service = MicrotechAnsprechpartnerService(erp=erp)

            seen_local_address_ids: list[int] = []
            has_range = anschrift_service.set_range(
                from_range=[customer_erp_nr, 0],
                to_range=[customer_erp_nr, 999],
            )
            if has_range:
                while not anschrift_service.range_eof():
                    ans_id = _to_int(anschrift_service.get_field("ID"))
                    ans_nr = _to_int(anschrift_service.get_field("AnsNr"))
                    if ans_nr is None:
                        anschrift_service.range_next()
                        continue

                    contact_data = self._load_first_contact(
                        ansprechpartner_service=ansprechpartner_service,
                        customer_erp_nr=customer_erp_nr,
                        ans_nr=ans_nr,
                    )

                    address_email = _to_str(anschrift_service.get_field("EMail1")) or contact_data["email"]
                    address_defaults = {
                        "erp_nr": _to_int(customer_erp_nr),
                        "erp_ans_id": ans_id,
                        "erp_ans_nr": ans_nr,
                        "erp_asp_id": contact_data["asp_id"],
                        "erp_asp_nr": contact_data["asp_nr"],
                        "name1": _to_str(anschrift_service.get_field("Na1")),
                        "name2": _to_str(anschrift_service.get_field("Na2")),
                        "name3": _to_str(anschrift_service.get_field("Na3")),
                        "department": contact_data["department"],
                        "street": _to_str(anschrift_service.get_field("Str")),
                        "postal_code": _to_str(anschrift_service.get_field("PLZ")),
                        "city": _to_str(anschrift_service.get_field("Ort")),
                        "country_code": _to_str(anschrift_service.get_field("Land")),
                        "email": address_email,
                        "title": contact_data["title"],
                        "first_name": contact_data["first_name"],
                        "last_name": contact_data["last_name"],
                        "phone": contact_data["phone"],
                        "is_shipping": ans_nr == standard_shipping_nr,
                        "is_invoice": ans_nr == standard_invoice_nr,
                    }
                    address = self._upsert_local_address(
                        customer=customer,
                        ans_id=ans_id,
                        ans_nr=ans_nr,
                        defaults=address_defaults,
                    )
                    seen_local_address_ids.append(address.pk)
                    anschrift_service.range_next()

            if seen_local_address_ids:
                customer.addresses.exclude(pk__in=seen_local_address_ids).delete()
            else:
                logger.warning("Kunde {} hat keine Anschriften in Microtech.", customer_erp_nr)

            return customer

    def _upsert_local_address(
        self,
        *,
        customer: Customer,
        ans_id: int | None,
        ans_nr: int,
        defaults: dict[str, Any],
    ) -> Address:
        qs = Address.objects.filter(customer=customer)
        address = qs.filter(erp_ans_id=ans_id).first() if ans_id is not None else None
        if not address:
            address = qs.filter(erp_ans_nr=ans_nr).first()
        if not address:
            address = Address(customer=customer)

        for field_name, field_value in defaults.items():
            setattr(address, field_name, field_value)
        address.save()
        return address

    def _load_first_contact(
        self,
        *,
        ansprechpartner_service: MicrotechAnsprechpartnerService,
        customer_erp_nr: str,
        ans_nr: int,
    ) -> dict[str, Any]:
        has_contacts = ansprechpartner_service.set_range(
            from_range=[customer_erp_nr, ans_nr, 0],
            to_range=[customer_erp_nr, ans_nr, 20],
        )
        if not has_contacts:
            return {
                "asp_id": None,
                "asp_nr": None,
                "title": "",
                "first_name": "",
                "last_name": "",
                "email": "",
                "phone": "",
                "department": "",
            }

        return {
            "asp_id": _to_int(ansprechpartner_service.get_field("ID")),
            "asp_nr": _to_int(ansprechpartner_service.get_field("AspNr")),
            "title": _to_str(ansprechpartner_service.get_field("Anr")),
            "first_name": _to_str(ansprechpartner_service.get_field("VNa")),
            "last_name": _to_str(ansprechpartner_service.get_field("NNa")),
            "email": _to_str(ansprechpartner_service.get_field("EMail1")),
            "phone": _to_str(ansprechpartner_service.get_field("Tel1")),
            "department": _to_str(ansprechpartner_service.get_field("Abt")),
        }
