"""Explicit Shopware ↔ microtech assignments from the manual mapping board."""

from __future__ import annotations

from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction

from core.services.base import BaseService
from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
from customer.services.customer_merge import (
    CustomerMergeSearchService,
    CustomerSyncDirectionService,
    _to_str,
)


class CustomerMappingService(BaseService):
    @staticmethod
    def _microtech_customer(job_id: int, erp_nr: str) -> dict:
        status = CustomerMergeSearchService().get_microtech_search_job_status(job_id)
        if status.get("state") != "succeeded":
            raise ValueError("Die microtech-Suche ist noch nicht abgeschlossen. Bitte erneut suchen.")
        customer = status.get("data")
        if not isinstance(customer, dict) or _to_str(customer.get("erp_nr")) != erp_nr:
            raise ValueError("Das ausgewählte microtech-Konto stimmt nicht mit der Suche überein.")
        return customer

    @staticmethod
    def _shopware_customer(shopware_id: str) -> dict:
        from orders.services.order_sync import _normalize_entity
        from shopware.services import CustomerService

        response = CustomerService().get_by_id(shopware_id)
        data = (response or {}).get("data") or []
        if not data:
            raise ValueError("Das Shopware-Konto wurde nicht gefunden.")
        raw = _normalize_entity(data[0])
        if _to_str(raw.get("id")).lower() != shopware_id.lower():
            raise ValueError("Das geladene Shopware-Konto stimmt nicht mit der Auswahl überein.")
        return raw

    def link_customer(self, *, shopware_id: str, erp_nr: str, job_id: int, user_id: int) -> dict:
        shopware_id = _to_str(shopware_id).lower()
        erp_nr = _to_str(erp_nr)
        if not shopware_id or not erp_nr:
            raise ValueError("Bitte ein Shopware- und ein microtech-Konto auswählen.")
        microtech = self._microtech_customer(job_id, erp_nr)
        shopware = self._shopware_customer(shopware_id)
        with transaction.atomic():
            customer = Customer.objects.select_for_update().filter(erp_nr=erp_nr).first()
            if Customer.objects.filter(api_id__iexact=shopware_id).exclude(erp_nr=erp_nr).exists():
                raise ValueError("Das Shopware-Konto ist bereits einer anderen AdrNr zugeordnet.")
            if customer and customer.api_id and customer.api_id.lower() != shopware_id:
                raise ValueError("Diese AdrNr ist bereits einem anderen Shopware-Konto zugeordnet.")
            if not customer:
                customer = Customer(erp_nr=erp_nr)
            customer.api_id = shopware_id
            if not customer.name:
                customer.name = _to_str(microtech.get("name")) or _to_str(shopware.get("company"))
            if not customer.email:
                customer.email = _to_str(shopware.get("email"))
            customer.save()
            LogEntry.objects.log_actions(
                user_id=user_id, queryset=Customer.objects.filter(pk=customer.pk),
                action_flag=CHANGE,
                change_message=f"Manuelle Zuordnung: SW6 {shopware_id} ↔ microtech AdrNr {erp_nr}",
            )
        return {"customer_id": customer.pk, "shopware_id": shopware_id, "erp_nr": erp_nr}

    def link_address(
        self, *, customer_id: int, shopware_address_id: str, ans_nr: int,
        asp_nr: int | None, job_id: int, user_id: int,
    ) -> dict:
        shopware_address_id = _to_str(shopware_address_id).lower()
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer or not customer.api_id:
            raise ValueError("Bitte zuerst die Kundenkonten zuordnen.")
        microtech = self._microtech_customer(job_id, customer.erp_nr)
        mt_address = next(
            (a for a in microtech.get("addresses", []) if str(a.get("ans_nr")) == str(ans_nr)), None,
        )
        if mt_address is None:
            raise ValueError("Die microtech-Anschrift gehört nicht zum ausgewählten Konto.")
        if asp_nr is not None and str(asp_nr) not in {
            str(c.get("asp_nr")) for c in mt_address.get("contacts", [])
        }:
            raise ValueError("Der Ansprechpartner gehört nicht zur ausgewählten Anschrift.")

        raw = self._shopware_customer(customer.api_id)
        addresses = raw.get("addresses") or []
        if isinstance(addresses, dict):
            addresses = addresses.get("data") or []
        from orders.services.order_sync import _normalize_entity
        addresses = _normalize_entity(addresses) if isinstance(addresses, list) else []
        sw_address = next(
            (a for a in addresses if _to_str(a.get("id")).lower() == shopware_address_id), None,
        )
        if sw_address is None:
            raise ValueError("Die Shopware-Adresse gehört nicht zum ausgewählten Konto.")

        with transaction.atomic():
            if Address.objects.filter(api_id__iexact=shopware_address_id).exclude(customer=customer).exists():
                raise ValueError("Die Shopware-Adresse ist bereits einem anderen Kunden zugeordnet.")
            address = Address.objects.select_for_update().filter(
                customer=customer, api_id__iexact=shopware_address_id,
            ).first()
            if not address:
                address = Address(customer=customer)
            CustomerSyncDirectionService._apply_shopware_address(
                address, sw_address, customer=customer,
                default_billing_id=_to_str(raw.get("defaultBillingAddressId")),
                default_shipping_id=_to_str(raw.get("defaultShippingAddressId")),
            )
            existing = Address.objects.filter(
                customer=customer, erp_ans_nr=ans_nr, erp_asp_nr=asp_nr,
            ).exclude(pk=address.pk).first()
            if existing:
                from customer.services.address_recommendations import BUSINESS_FIELDS, identical_addresses
                if not identical_addresses(
                    {field: getattr(existing, field) for field in BUSINESS_FIELDS},
                    {field: getattr(address, field) for field in BUSINESS_FIELDS},
                ):
                    raise ValueError("Diese microtech-Anschrift mit Ansprechpartner ist bereits einer anderen Adresse zugeordnet.")
            address.erp_nr = int(customer.erp_nr) if customer.erp_nr.isdigit() else None
            address.erp_ans_nr = ans_nr
            address.erp_asp_nr = asp_nr
            address.erp_ans_id = None
            address.erp_asp_id = None
            address.erp_combined_id = None
            address.save()
            LogEntry.objects.log_actions(
                user_id=user_id, queryset=Address.objects.filter(pk=address.pk),
                action_flag=CHANGE,
                change_message=(f"Manuelle Zuordnung: SW6-Adresse {shopware_address_id} ↔ "
                                f"microtech AnsNr {ans_nr}, AnspNr {asp_nr}"),
            )
        return {"address_id": address.pk, "shopware_address_id": shopware_address_id,
                "ans_nr": ans_nr, "asp_nr": asp_nr}

    def sync_customer(self, *, customer_id: int, user_id: int) -> dict:
        """Send only verified manual mappings and compare the remote identity afterward."""
        from microtech.services import microtech_connection

        customer = Customer.objects.prefetch_related("addresses").filter(pk=customer_id).first()
        if not customer or not customer.api_id:
            raise ValueError("Bitte zuerst die Kundenkonten zuordnen.")
        shopware = self._shopware_customer(customer.api_id)
        mapped = list(customer.addresses.exclude(api_id="").filter(erp_ans_nr__isnull=False))
        shopware_addresses = shopware.get("addresses") or []
        if isinstance(shopware_addresses, dict):
            shopware_addresses = shopware_addresses.get("data") or []
        from orders.services.order_sync import _normalize_entity
        shopware_addresses = _normalize_entity(shopware_addresses) if isinstance(shopware_addresses, list) else []
        shopware_address_ids = {
            _to_str(address.get("id")).lower() for address in shopware_addresses
            if isinstance(address, dict)
        }
        if any(address.api_id.lower() not in shopware_address_ids for address in mapped):
            raise ValueError("Eine zugeordnete Shopware-Adresse existiert nicht mehr. Bitte die Zuordnung prüfen.")
        by_sw_id = {address.api_id.lower(): address for address in mapped}
        shipping_id = _to_str(shopware.get("defaultShippingAddressId")).lower()
        billing_id = _to_str(shopware.get("defaultBillingAddressId")).lower()
        shipping = by_sw_id.get(shipping_id)
        billing = by_sw_id.get(billing_id)
        if not shipping or not billing:
            raise ValueError("Bitte zuerst beide Shopware-Standardadressen einer microtech-Anschrift zuordnen.")
        if shipping.erp_ans_nr == billing.erp_ans_nr and shipping.erp_asp_nr != billing.erp_asp_nr:
            raise ValueError(
                "Liefer- und Rechnungsadresse verwenden dieselbe Anschrift mit verschiedenen Ansprechpartnern. "
                "Das kann microtech nicht als zwei Standard-Ansprechpartner abbilden."
            )
        postal_fields = ("name1", "name2", "name3", "street", "postal_code", "city", "country_code")
        by_ans_nr: dict[int, Address] = {}
        contact_by_ans_nr: dict[int, int | None] = {}
        for address in mapped:
            previous = by_ans_nr.setdefault(address.erp_ans_nr, address)
            if any(_to_str(getattr(previous, field)).casefold() != _to_str(getattr(address, field)).casefold()
                   for field in postal_fields):
                raise ValueError(f"AnsNr {address.erp_ans_nr} wurde verschiedenen Anschriften zugeordnet.")
            if address.erp_ans_nr in contact_by_ans_nr and contact_by_ans_nr[address.erp_ans_nr] != address.erp_asp_nr:
                raise ValueError(
                    f"AnsNr {address.erp_ans_nr} hat mehrere zugeordnete Ansprechpartner. "
                    "microtech kann für eine Anschrift nur einen Standard-Ansprechpartner führen."
                )
            contact_by_ans_nr[address.erp_ans_nr] = address.erp_asp_nr

        upsert = CustomerUpsertMicrotechService()
        with microtech_connection() as client:
            before = upsert._customer_from_result(client.request_customer(customer.erp_nr))
            if _to_str(before.get("customerNumber")) != customer.erp_nr:
                raise ValueError("Das microtech-Konto wurde nicht gefunden. Es wird kein neues Konto angelegt.")
            remote_addresses = {
                int(a["addressSubNumber"]): a for a in before.get("addresses") or []
                if isinstance(a, dict) and a.get("addressSubNumber") is not None
            }
            for address in mapped:
                remote = remote_addresses.get(address.erp_ans_nr)
                if remote is None:
                    raise ValueError(f"AnsNr {address.erp_ans_nr} ist in microtech nicht mehr vorhanden. Bitte neu suchen.")
                if address.erp_asp_nr is not None and address.erp_asp_nr not in {
                    int(c["contactNumber"]) for c in remote.get("contacts") or []
                    if isinstance(c, dict) and c.get("contactNumber") is not None
                }:
                    raise ValueError(
                        f"Ansprechpartner {address.erp_asp_nr} gehört in microtech nicht mehr zur AnsNr {address.erp_ans_nr}."
                    )

            upsert.upsert_customer(customer, shipping_address=shipping, billing_address=billing, erp=client)
            default_numbers = {shipping.erp_ans_nr, billing.erp_ans_nr}
            for ans_nr, address in by_ans_nr.items():
                if ans_nr in default_numbers:
                    continue
                payload = upsert._build_postal_address_input(
                    address=address, is_shipping=False, is_invoice=False,
                    na1_mode="auto", na1_static_value="", include_email=False,
                )
                payload.pop("isDefaultShipping", None)
                payload.pop("isDefaultBilling", None)
                client.update_postal_address(int(customer.erp_nr), ans_nr, payload)
            for address in mapped:
                if address.erp_ans_nr in default_numbers:
                    continue
                if address is not by_ans_nr[address.erp_ans_nr]:
                    continue
                upsert._clear_existing_default_contact_flags(
                    client=client, address_number=int(customer.erp_nr),
                    customer=before, address_sub_number=address.erp_ans_nr,
                    selected_contact_number=address.erp_asp_nr,
                )
                if address.erp_asp_nr is None:
                    continue
                upsert._upsert_contact_person_graphql(
                    client=client, address_number=int(customer.erp_nr),
                    address_sub_number=address.erp_ans_nr, address=address,
                    is_default=True,
                )

            after = upsert._customer_from_result(client.request_customer(customer.erp_nr))
            if _to_str(after.get("customerNumber")) != customer.erp_nr:
                raise ValueError("microtech hat nach der Übertragung kein prüfbares Konto geliefert.")
            after_addresses = {
                int(a["addressSubNumber"]): a for a in after.get("addresses") or []
                if isinstance(a, dict) and a.get("addressSubNumber") is not None
            }
            if _to_str(after.get("defaultShippingAddressNumber")) != str(shipping.erp_ans_nr) or \
               _to_str(after.get("defaultBillingAddressNumber")) != str(billing.erp_ans_nr):
                raise ValueError("Die microtech-Standardadressen stimmen nach der Übertragung nicht mit der Auswahl überein.")
            for address in mapped:
                remote = after_addresses.get(address.erp_ans_nr)
                if remote is None:
                    raise ValueError(f"AnsNr {address.erp_ans_nr} fehlt nach der Übertragung in microtech.")
                for local_field, remote_field in (
                    ("street", "street"), ("postal_code", "zipCode"),
                    ("city", "city"), ("country_code", "country"),
                ):
                    value = _to_str(getattr(address, local_field))
                    if value and value.casefold() != _to_str(remote.get(remote_field)).casefold():
                        raise ValueError(
                            f"AnsNr {address.erp_ans_nr}: {local_field} stimmt nach der Übertragung nicht überein."
                        )
                contacts = {
                    int(c["contactNumber"]): c for c in remote.get("contacts") or []
                    if isinstance(c, dict) and c.get("contactNumber") is not None
                }
                if address.erp_asp_nr is not None:
                    contact = contacts.get(address.erp_asp_nr)
                    if contact is None:
                        raise ValueError(
                            f"Ansprechpartner {address.erp_asp_nr} fehlt nach der Übertragung an AnsNr {address.erp_ans_nr}."
                        )
                    for local_field, remote_field in (
                        ("first_name", "firstName"), ("last_name", "lastName"),
                        ("email", "email"), ("phone", "phone"),
                    ):
                        value = _to_str(getattr(address, local_field))
                        if value and value.casefold() != _to_str(contact.get(remote_field)).casefold():
                            raise ValueError(
                                f"Ansprechpartner {address.erp_asp_nr} an AnsNr {address.erp_ans_nr}: "
                                f"{local_field} stimmt nach der Übertragung nicht überein."
                            )
            for role, selected in (("isDefaultShipping", shipping), ("isDefaultBilling", billing)):
                actual = {
                    number for number, remote in after_addresses.items() if remote.get(role)
                }
                if actual != {selected.erp_ans_nr}:
                    raise ValueError(f"microtech hat nach der Übertragung widersprüchliche {role}-Kennzeichen.")
            for ans_nr, selected_contact in contact_by_ans_nr.items():
                actual_defaults = {
                    int(c["contactNumber"]) for c in after_addresses[ans_nr].get("contacts") or []
                    if isinstance(c, dict) and c.get("isDefault") and c.get("contactNumber") is not None
                }
                expected_defaults = {selected_contact} if selected_contact is not None else set()
                if actual_defaults != expected_defaults:
                    raise ValueError(
                        f"AnsNr {ans_nr}: Der Standard-Ansprechpartner in microtech stimmt nicht mit der Zuordnung überein."
                    )
        LogEntry.objects.log_actions(
            user_id=user_id, queryset=Customer.objects.filter(pk=customer.pk), action_flag=CHANGE,
            change_message=f"Manuelle Zuordnung nach microtech übertragen: {len(mapped)} Adressen geprüft",
        )
        return {"customer_id": customer.pk, "addresses_checked": len(mapped)}
