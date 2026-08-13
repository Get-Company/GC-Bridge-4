from __future__ import annotations

from typing import Any

from django.db import transaction

from core.services import BaseService
from customer.models import Address, Customer
from microtech.models import MicrotechGraphQLJob
from microtech.services import MicrotechGraphQLClientService, MicrotechJobSentinelService
from orders.models import Order

CONTINUATION_NAME = "order_customer_change_apply"
CONTEXT_SOURCE = "order_customer_change"


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


class OrderCustomerChangeService(BaseService):
    """Assign an order to a Microtech customer returned by a Sentinel read job."""

    model = Order

    active_job_statuses = (
        MicrotechGraphQLJob.Status.QUEUED,
        MicrotechGraphQLJob.Status.SUBMITTED,
        MicrotechGraphQLJob.Status.RUNNING,
        MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
    )

    def request_change(self, *, order: Order, erp_nr: str) -> MicrotechGraphQLJob:
        erp_nr = self._clean_erp_nr(erp_nr)
        active_job = (
            MicrotechGraphQLJob.objects.filter(
                kind=MicrotechGraphQLJob.Kind.CUSTOMER_READ,
                operation="requestCustomer",
                status__in=self.active_job_statuses,
                context__source=CONTEXT_SOURCE,
                context__order_id=order.pk,
            )
            .order_by("-created_at")
            .first()
        )
        if active_job is not None:
            raise ValueError(
                f"Für diese Bestellung wird AdrNr {active_job.context.get('erp_nr', '')} bereits geladen "
                f"(Sentinel-Job #{active_job.pk})."
            )

        client = MicrotechGraphQLClientService()
        return MicrotechJobSentinelService().submit_wrapper_job(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_READ,
            operation="requestCustomer",
            submit=lambda: client.submit_request_customer(erp_nr),
            request_payload={"customerNumber": erp_nr},
            context={
                "source": CONTEXT_SOURCE,
                "order_id": order.pk,
                "erp_nr": erp_nr,
            },
            continuation=CONTINUATION_NAME,
            next_step="Lade Kundendaten und Standardadressen aus Microtech.",
            delete_after_completion=False,
        )

    def apply_result(self, job: MicrotechGraphQLJob) -> None:
        """Continuation: import the requested customer and replace the order links."""

        context = job.context or {}
        if context.get("source") != CONTEXT_SOURCE:
            return
        order_id = _to_int(context.get("order_id"))
        requested_erp_nr = self._clean_erp_nr(context.get("erp_nr"))
        if order_id is None:
            raise ValueError("Sentinel-Job enthält keine Bestellung.")

        # A later click supersedes an older result that reaches the continuation
        # queue afterwards. This prevents an old response from reverting a newer
        # AdrNr selection.
        if MicrotechGraphQLJob.objects.filter(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_READ,
            operation="requestCustomer",
            context__source=CONTEXT_SOURCE,
            context__order_id=order_id,
            status__in=(*self.active_job_statuses, MicrotechGraphQLJob.Status.SUCCEEDED),
            created_at__gt=job.created_at,
        ).exists():
            job.next_step = "Durch eine neuere AdrNr-Änderung überholt."
            job.save(update_fields=("next_step", "updated_at"))
            return

        customer_payload = self._customer_from_result(job.result_payload or {})
        returned_erp_nr = _to_str(customer_payload.get("customerNumber"))
        if not returned_erp_nr:
            raise ValueError(f"Kunde mit AdrNr {requested_erp_nr} wurde in Microtech nicht gefunden.")
        if not self._same_erp_number(requested_erp_nr, returned_erp_nr):
            raise ValueError(
                f"Microtech lieferte AdrNr {returned_erp_nr} statt der angeforderten AdrNr {requested_erp_nr}."
            )

        with transaction.atomic():
            order = Order.objects.select_for_update().filter(pk=order_id).first()
            if order is None:
                return
            customer, shipping_address, billing_address = self._import_customer(customer_payload)
            order.customer = customer
            order.shipping_address = shipping_address
            order.billing_address = billing_address
            order.save(update_fields=("customer", "shipping_address", "billing_address", "updated_at"))

        job.next_step = "Kunde sowie Rechnungs- und Lieferanschrift übernommen."
        job.save(update_fields=("next_step", "updated_at"))

    def _import_customer(self, payload: dict[str, Any]) -> tuple[Customer, Address, Address]:
        erp_nr = _to_str(payload.get("customerNumber"))
        if not erp_nr:
            raise ValueError("Microtech-Kunde enthält keine AdrNr.")

        first_name = _to_str(payload.get("firstName"))
        last_name = _to_str(payload.get("lastName"))
        customer, _ = Customer.objects.get_or_create(erp_nr=erp_nr)
        customer.name = _to_str(payload.get("name1")) or f"{first_name} {last_name}".strip()
        customer.email = _to_str(payload.get("email"))
        customer.erp_id = _to_int(payload.get("erpAddressNumber"))
        customer.save(update_fields=("name", "email", "erp_id", "updated_at"))

        default_shipping_nr = _to_int(payload.get("defaultShippingAddressNumber"))
        default_billing_nr = _to_int(payload.get("defaultBillingAddressNumber"))
        imported_addresses: list[Address] = []
        payload_addresses = [entry for entry in payload.get("addresses") or [] if isinstance(entry, dict)]
        if not payload_addresses:
            payload_addresses = [payload]

        for address_payload in payload_addresses:
            address_sub_number = _to_int(address_payload.get("addressSubNumber"))
            is_shipping = bool(address_payload.get("isDefaultShipping")) or (
                address_sub_number is not None and address_sub_number == default_shipping_nr
            )
            is_billing = bool(address_payload.get("isDefaultBilling")) or (
                address_sub_number is not None and address_sub_number == default_billing_nr
            )
            contacts = [entry for entry in address_payload.get("contacts") or [] if isinstance(entry, dict)]
            if not contacts:
                contacts = [{}]
            for contact_payload in contacts:
                imported_addresses.append(
                    self._upsert_address(
                        customer=customer,
                        customer_erp_nr=_to_int(payload.get("erpAddressNumber")) or _to_int(erp_nr),
                        address_sub_number=address_sub_number,
                        contact_number=_to_int(contact_payload.get("contactNumber")),
                        values={
                            "name1": _to_str(address_payload.get("name1")) or _to_str(payload.get("name1")),
                            "name2": _to_str(address_payload.get("name2")) or _to_str(payload.get("name2")),
                            "name3": _to_str(address_payload.get("name3")) or _to_str(payload.get("name3")),
                            "department": _to_str(contact_payload.get("department"))
                            or _to_str(address_payload.get("department"))
                            or _to_str(payload.get("department")),
                            "street": _to_str(address_payload.get("street")) or _to_str(payload.get("street")),
                            "postal_code": _to_str(address_payload.get("zipCode")) or _to_str(payload.get("zipCode")),
                            "city": _to_str(address_payload.get("city")) or _to_str(payload.get("city")),
                            "country_code": _to_str(address_payload.get("country")) or _to_str(payload.get("country")),
                            "email": _to_str(address_payload.get("email"))
                            or _to_str(contact_payload.get("email"))
                            or _to_str(payload.get("email")),
                            "title": _to_str(contact_payload.get("salutation")) or _to_str(payload.get("salutation")),
                            "first_name": _to_str(contact_payload.get("firstName")) or first_name,
                            "last_name": _to_str(contact_payload.get("lastName")) or last_name,
                            "phone": _to_str(address_payload.get("phone"))
                            or _to_str(contact_payload.get("phone"))
                            or _to_str(payload.get("phone")),
                            "is_shipping": is_shipping,
                            "is_invoice": is_billing,
                        },
                    )
                )

        shipping_address = next((address for address in imported_addresses if address.is_shipping), imported_addresses[0])
        billing_address = next((address for address in imported_addresses if address.is_invoice), shipping_address)
        customer.addresses.filter(is_shipping=True).exclude(pk=shipping_address.pk).update(is_shipping=False)
        customer.addresses.filter(is_invoice=True).exclude(pk=billing_address.pk).update(is_invoice=False)
        if not shipping_address.is_shipping:
            shipping_address.is_shipping = True
            shipping_address.save(update_fields=("is_shipping", "updated_at"))
        if not billing_address.is_invoice:
            billing_address.is_invoice = True
            billing_address.save(update_fields=("is_invoice", "updated_at"))
        return customer, shipping_address, billing_address

    @staticmethod
    def _upsert_address(
        *,
        customer: Customer,
        customer_erp_nr: int | None,
        address_sub_number: int | None,
        contact_number: int | None,
        values: dict[str, Any],
    ) -> Address:
        queryset = customer.addresses.all()
        address = None
        if address_sub_number is not None:
            if contact_number is not None:
                address = queryset.filter(erp_ans_nr=address_sub_number, erp_asp_nr=contact_number).first()
            else:
                address = queryset.filter(erp_ans_nr=address_sub_number, erp_asp_nr__isnull=True).first()
        if address is None:
            address = Address(customer=customer)

        address.erp_nr = customer_erp_nr
        address.erp_ans_nr = address_sub_number
        address.erp_asp_nr = contact_number
        for name, value in values.items():
            setattr(address, name, value)
        address.save()
        return address

    @classmethod
    def _customer_from_result(cls, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        customer = payload.get("customer")
        if isinstance(customer, dict):
            return customer
        for value in payload.values():
            customer = cls._customer_from_result(value)
            if customer:
                return customer
        return {}

    @staticmethod
    def _clean_erp_nr(value: Any) -> str:
        erp_nr = _to_str(value)
        if not erp_nr:
            raise ValueError("AdrNr ist erforderlich.")
        if not erp_nr.isdigit():
            raise ValueError("AdrNr darf nur Ziffern enthalten.")
        return erp_nr

    @staticmethod
    def _same_erp_number(first: str, second: str) -> bool:
        return int(first) == int(second)
