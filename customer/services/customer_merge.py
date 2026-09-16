from __future__ import annotations

import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from loguru import logger

from django.db import models, transaction

from core.services import BaseService
from customer.models import Address, Customer
from orders.models import Order

_UUID_RE = re.compile(r"^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_MICROTECH_SEARCH_SOURCE = "customer_merge_search"
_MICROTECH_SEARCH_LIMIT = 20
_MICROTECH_NEW_CUSTOMER_THRESHOLD = 900_000


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_list(value: Any) -> list:
    """Safely coerce a value into a list of dicts."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            return data
        return list(value.values())
    return []


def _safe_attrs(item: Any) -> dict:
    """Extract attributes from a Shopware entity (handles both flat and JSON:API)."""
    if not isinstance(item, dict):
        return {}
    return item.get("attributes") or item


def _split_terms(value: Any) -> list[str]:
    """Split a comma-separated field into trimmed, non-empty terms."""
    return [term.strip() for term in _to_str(value).split(",") if term.strip()]


def _has_wildcard(value: Any) -> bool:
    """Whether the value uses the ``?`` placeholder (any character sequence)."""
    return "?" in _to_str(value)


def _wildcard_segments(value: Any) -> list[str]:
    """Literal segments of a ``?``-wildcard term, in order, without empties.

    ``"? Insulation ?"`` -> ``["Insulation"]`` (contains), ``"JACKSON ?"`` ->
    ``["JACKSON"]`` (prefix), ``"?@x.de"`` -> ``["@x.de"]`` (suffix). A plain
    term without ``?`` yields itself, so callers can always match per segment.
    """
    return [segment.strip() for segment in _to_str(value).split("?") if segment.strip()]


class CustomerMergeSearchService(BaseService):
    """Searches for customer data across Django, Shopware 6, and Microtech."""

    def resolve_shopware_customer_id_erp_numbers(self, *, customer_id: str = "") -> list[str]:
        """Resolve exact SW6 customer IDs to their customer numbers."""
        customer_ids = [value for value in _split_terms(customer_id) if _UUID_RE.fullmatch(value)]
        if not customer_ids:
            return []

        try:
            from shopware.services import Criteria, CustomerService, EqualsFilter

            service = CustomerService()
        except Exception as exc:
            logger.warning("Shopware ID resolve setup failed: {}", exc)
            return []

        customer_numbers: list[str] = []

        def add_customer_numbers(response: Any) -> None:
            for item in (response or {}).get("data", []) or []:
                number = _to_str(_safe_attrs(item).get("customerNumber"))
                if number and number not in customer_numbers:
                    customer_numbers.append(number)

        for value in customer_ids[:_MICROTECH_SEARCH_LIMIT]:
            try:
                add_customer_numbers(service.get_by_id(value))
            except Exception as exc:
                logger.warning("Shopware customer ID resolve failed: {}", exc)

        return customer_numbers

    def resolve_django_erp_numbers(
        self,
        *,
        customer_number: str = "",
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        company: str = "",
        street: str = "",
        postal_code: str = "",
        city: str = "",
    ) -> list[str]:
        """Resolve matching customer numbers from the GC-Bridge database."""
        customer_number = _to_str(customer_number)
        email = _to_str(email)
        first_name = _to_str(first_name)
        last_name = _to_str(last_name)
        company = _to_str(company)
        street = _to_str(street)
        postal_code = _to_str(postal_code)
        city = _to_str(city)

        numbers = _split_terms(customer_number)
        filters = models.Q()
        used = False
        if numbers:
            used = True
            number_q = models.Q()
            for number in numbers:
                number_q |= models.Q(erp_nr__iexact=number)
            filters &= number_q
        if email:
            used = True
            if _has_wildcard(email):
                for segment in _wildcard_segments(email):
                    filters &= models.Q(email__icontains=segment) | models.Q(
                        addresses__email__icontains=segment
                    )
            else:
                filters &= models.Q(email__iexact=email) | models.Q(addresses__email__iexact=email)
        for segment in _wildcard_segments(first_name):
            used = True
            filters &= models.Q(addresses__first_name__icontains=segment)
        for segment in _wildcard_segments(last_name):
            used = True
            filters &= models.Q(addresses__last_name__icontains=segment)
        for segment in _wildcard_segments(company):
            used = True
            filters &= models.Q(name__icontains=segment) | models.Q(
                addresses__name1__icontains=segment
            )
        for segment in _wildcard_segments(street):
            used = True
            filters &= models.Q(addresses__street__icontains=segment)
        for segment in _wildcard_segments(postal_code):
            used = True
            filters &= models.Q(addresses__postal_code__icontains=segment)
        for segment in _wildcard_segments(city):
            used = True
            filters &= models.Q(addresses__city__icontains=segment)

        if not used:
            return []

        try:
            return list(
                Customer.objects.filter(filters)
                .distinct()
                .order_by("erp_nr")
                .values_list("erp_nr", flat=True)[:_MICROTECH_SEARCH_LIMIT]
            )
        except Exception as exc:
            logger.error("GC-Bridge customer resolve failed: {}", exc)
            return []

    def resolve_shopware_erp_numbers(
        self,
        *,
        customer_number: str = "",
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        company: str = "",
        street: str = "",
        postal_code: str = "",
        city: str = "",
    ) -> list[str]:
        """Resolve matching customer numbers from Shopware 6.

        Supports comma-separated customer numbers, ``?`` wildcards (matched with
        Shopware ``contains`` filters per literal segment) and a company search.
        """
        try:
            from shopware.services import ContainsFilter, Criteria, CustomerService, EqualsFilter
            from lib_shopware6_api_base import MultiFilter

            criteria = Criteria(limit=_MICROTECH_SEARCH_LIMIT)
            numbers = _split_terms(customer_number)
            if len(numbers) == 1:
                criteria.filter.append(EqualsFilter(field="customerNumber", value=numbers[0]))
            elif numbers:
                criteria.filter.append(
                    MultiFilter(
                        operator="OR",
                        queries=[EqualsFilter(field="customerNumber", value=n) for n in numbers],
                    )
                )

            email = _to_str(email)
            if email:
                if _has_wildcard(email):
                    for segment in _wildcard_segments(email):
                        criteria.filter.append(ContainsFilter(field="email", value=segment))
                else:
                    criteria.filter.append(EqualsFilter(field="email", value=email))

            for segment in _wildcard_segments(first_name):
                criteria.filter.append(ContainsFilter(field="firstName", value=segment))
            for segment in _wildcard_segments(last_name):
                criteria.filter.append(ContainsFilter(field="lastName", value=segment))
            for segment in _wildcard_segments(company):
                criteria.filter.append(
                    MultiFilter(
                        operator="OR",
                        queries=[
                            ContainsFilter(field="company", value=segment),
                            ContainsFilter(field="addresses.company", value=segment),
                        ],
                    )
                )
            for segment in _wildcard_segments(street):
                criteria.filter.append(ContainsFilter(field="addresses.street", value=segment))
            for segment in _wildcard_segments(postal_code):
                criteria.filter.append(ContainsFilter(field="addresses.zipcode", value=segment))
            for segment in _wildcard_segments(city):
                criteria.filter.append(ContainsFilter(field="addresses.city", value=segment))

            if not criteria.filter:
                return []

            response = CustomerService().request_post("/search/customer", payload=criteria)
        except Exception as exc:
            logger.warning("Shopware customer resolve failed: {}", exc)
            return []

        customer_numbers: list[str] = []
        for item in (response or {}).get("data", []) or []:
            resolved = _to_str(_safe_attrs(item).get("customerNumber"))
            if resolved and resolved not in customer_numbers:
                customer_numbers.append(resolved)
        return customer_numbers

    def resolve_query(self, term: str) -> list[str]:
        """Resolve ERP numbers locally and in Shopware.

        Microtech is queried separately through the Sentinel so the admin request
        never performs a blocking dataset read.
        """
        term = term.strip()
        if not term:
            return []

        # 1) Numeric → treat as ERP-Nr directly
        if term.isdigit():
            return [term]

        # 2) UUID → look up in Django and Shopware
        if _UUID_RE.match(term):
            erp_nrs: set[str] = set()
            # Django lookup
            cust = Customer.objects.filter(api_id=term).first()
            if cust:
                erp_nrs.add(cust.erp_nr)
            # Shopware lookup
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                response = service.get_by_id(term)
                for item in (response or {}).get("data", []) or []:
                    attrs = _safe_attrs(item)
                    cn = _to_str(attrs.get("customerNumber"))
                    if cn:
                        erp_nrs.add(cn)
            except Exception as exc:
                logger.warning("Shopware UUID resolve failed for {}: {}", term, exc)
            return sorted(erp_nrs) if erp_nrs else [term]

        # 3) ERP number, customer name or contact person → Django + Shopware
        erp_nrs: set[str] = set()
        for cust in Customer.objects.filter(
            models.Q(erp_nr__iexact=term)
            | models.Q(name__icontains=term)
            | models.Q(email__icontains=term)
            | models.Q(addresses__first_name__icontains=term)
            | models.Q(addresses__last_name__icontains=term)
        ).distinct()[:_MICROTECH_SEARCH_LIMIT]:
            erp_nrs.add(cust.erp_nr)

        try:
            from shopware.services import CustomerService

            service = CustomerService()

            # Shopware 6 customerNumber is an explicit search key. Resolve it
            # before performing the fuzzy first-/last-name search.
            customer_number_response = service.get_by_customer_number(term)
            for item in (customer_number_response or {}).get("data", []) or []:
                attrs = _safe_attrs(item)
                customer_number = _to_str(attrs.get("customerNumber"))
                if customer_number:
                    erp_nrs.add(customer_number)

            response = service.search_by_name(term, limit=_MICROTECH_SEARCH_LIMIT)
            for item in (response or {}).get("data", []) or []:
                attrs = _safe_attrs(item)
                customer_number = _to_str(attrs.get("customerNumber"))
                if customer_number:
                    erp_nrs.add(customer_number)
        except Exception as exc:
            logger.warning("Shopware name resolve failed for '{}': {}", term, exc)
        return sorted(erp_nrs)

    def start_microtech_resolution_search(
        self,
        term: str = "",
        *,
        customer_number: str = "",
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        company: str = "",
    ) -> list[dict[str, Any]]:
        """Queue exact Microtech lookups for known, existing customer numbers only.

        E-mail, company and name criteria are resolved exclusively in SW6 and
        GC-Bridge. Their AdrNr results are handed here as ``customer_number``;
        this prevents wildcard or broad GraphQL searches in Microtech.
        """
        del email, first_name, last_name, company
        numbers = _split_terms(customer_number) or _split_terms(term)
        jobs: list[dict[str, Any]] = []
        for number in self.microtech_candidate_numbers(numbers):
            result = self.start_microtech_customer_search(number, purpose="resolve")
            if not result.get("error") and not result.get("skipped"):
                jobs.append({"job_id": result["job_id"], "search_kind": "customer"})
        return jobs

    @staticmethod
    def is_microtech_existing_customer_number(value: Any) -> bool:
        """Whether an AdrNr can exist in Microtech rather than being a new customer."""
        number = _to_str(value)
        return number.isdigit() and int(number) < _MICROTECH_NEW_CUSTOMER_THRESHOLD

    @classmethod
    def microtech_candidate_numbers(cls, numbers: list[str]) -> list[str]:
        """Return unique existing AdrNr values which may be fetched from Microtech."""
        candidates: list[str] = []
        for number in numbers:
            number = _to_str(number)
            if cls.is_microtech_existing_customer_number(number) and number not in candidates:
                candidates.append(number)
        return candidates

    def _submit_address_records_search(self, term: str) -> list[dict[str, Any]]:
        """Queue a Microtech contains search on AdrNr, names and company (Na1)."""
        term = _to_str(term)
        if not term:
            return []
        try:
            from microtech.models import MicrotechGraphQLJob
            from microtech.services import MicrotechGraphQLClientService, MicrotechJobSentinelService

            client = MicrotechGraphQLClientService()
            job = MicrotechJobSentinelService().submit_wrapper_job(
                kind=MicrotechGraphQLJob.Kind.DATASET_RECORDS,
                operation="searchAddressRecords",
                submit=lambda: client.submit_search_address_records(term, _MICROTECH_SEARCH_LIMIT),
                request_payload={"search_term": term, "limit_per_dataset": _MICROTECH_SEARCH_LIMIT},
                context={
                    "source": _MICROTECH_SEARCH_SOURCE,
                    "purpose": "resolve",
                    "search_kind": "address_records",
                    "search_criteria": {"search_term": term},
                },
                continuation="",
                next_step="Warte auf Microtech-Suche.",
                delete_after_completion=False,
            )
        except Exception as exc:
            logger.warning("Microtech address search submit failed: {}", exc)
            return []
        return [{"job_id": job.pk, "search_kind": "address_records"}]

    @staticmethod
    def _microtech_resolution_requests(term: str) -> list[tuple[str, dict[str, Any]]]:
        """Return indexed DatasetReadInput payloads for a free-form name search."""
        prefix_end = f"{term}\uffff"
        quoted_term = term.replace("'", "''")
        return [
            (
                "suchbegriff",
                {
                    "dataset": "Adressen",
                    "indexField": "SuchBeg",
                    "range": {
                        "fromValues": [term, ""],
                        "toValues": [prefix_end, "\uffff"],
                    },
                    "fields": ["AdrNr", "AdrId", "SuchBeg", "Na1", "EMail1", "Status"],
                    "limit": _MICROTECH_SEARCH_LIMIT,
                },
            ),
            (
                "nachname",
                {
                    "dataset": "Ansprechpartner",
                    "indexField": "NNa",
                    "range": {
                        "fromValues": [term, ""],
                        "toValues": [prefix_end, "\uffff"],
                    },
                    "fields": ["AdrNr", "AnsNr", "AspNr", "VNa", "NNa", "EMail1"],
                    "limit": _MICROTECH_SEARCH_LIMIT,
                },
            ),
            (
                "vorname",
                {
                    "dataset": "Ansprechpartner",
                    "indexField": "NNa",
                    "range": {
                        "fromValues": ["", ""],
                        "toValues": ["\uffff", "\uffff"],
                    },
                    "filter": f"VNa = '{quoted_term}'",
                    "fields": ["AdrNr", "AnsNr", "AspNr", "VNa", "NNa", "EMail1"],
                    "limit": _MICROTECH_SEARCH_LIMIT,
                },
            ),
        ]

    def start_microtech_customer_search(
        self,
        erp_nr: str,
        *,
        purpose: str = "customer",
    ) -> dict[str, Any]:
        """Queue a typed ``requestCustomer`` read through the Sentinel."""
        erp_nr = _to_str(erp_nr)
        if not erp_nr:
            return {"error": "ERP-Nummer erforderlich."}
        if not self.is_microtech_existing_customer_number(erp_nr):
            return {"skipped": True}

        try:
            from microtech.models import MicrotechGraphQLJob
            from microtech.services import MicrotechGraphQLClientService, MicrotechJobSentinelService

            client = MicrotechGraphQLClientService()
            job = MicrotechJobSentinelService().submit_wrapper_job(
                kind=MicrotechGraphQLJob.Kind.CUSTOMER_READ,
                operation="requestCustomer",
                submit=lambda: client.submit_request_customer(erp_nr),
                request_payload={"customerNumber": erp_nr},
                context={
                    "source": _MICROTECH_SEARCH_SOURCE,
                    "purpose": purpose,
                    "erp_nr": erp_nr,
                },
                continuation="",
                next_step="Warte auf Microtech-Kundensuche.",
                delete_after_completion=False,
            )
        except Exception as exc:
            logger.error("Microtech customer search submit failed for {}: {}", erp_nr, exc)
            return {"error": str(exc)}
        return {"job_id": job.pk}

    def get_microtech_search_job_status(self, job_id: int) -> dict[str, Any]:
        """Return a public, merge-search-specific view of a Sentinel job."""
        from microtech.models import MicrotechGraphQLJob

        job = MicrotechGraphQLJob.objects.filter(pk=job_id).first()
        if not job or (job.context or {}).get("source") != _MICROTECH_SEARCH_SOURCE:
            return {"job_id": job_id, "state": "failed", "error": "Microtech-Suchauftrag nicht gefunden."}

        if job.status in {
            MicrotechGraphQLJob.Status.QUEUED,
            MicrotechGraphQLJob.Status.SUBMITTED,
            MicrotechGraphQLJob.Status.RUNNING,
            MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
        }:
            return {
                "job_id": job.pk,
                "state": "pending",
                "message": self._microtech_wait_message(job.status, job.operation),
            }

        if job.status != MicrotechGraphQLJob.Status.SUCCEEDED:
            return {
                "job_id": job.pk,
                "state": "failed",
                "error": job.error_message or "Microtech-Suche fehlgeschlagen.",
                "message": "Die Suche in Microtech konnte nicht abgeschlossen werden.",
            }

        if job.kind == MicrotechGraphQLJob.Kind.DATASET_RECORDS:
            if job.operation == "searchCustomers":
                customers = self._microtech_customers_from_search_result(job.result_payload or {})
                return {
                    "job_id": job.pk,
                    "state": "succeeded",
                    "message": f"{len(customers)} passende Kunden in Microtech gefunden.",
                    "result_count": len(customers),
                    "customers": customers,
                }
            if job.operation == "searchAddressRecords":
                erp_nrs = self._erp_numbers_from_address_search_result(job.result_payload or {})
                return {
                    "job_id": job.pk,
                    "state": "succeeded",
                    "message": f"{len(erp_nrs)} passende Kundennummern in Microtech gefunden.",
                    "result_count": len(erp_nrs),
                    "erp_nrs": erp_nrs,
                }
            erp_nrs = self._erp_numbers_from_dataset_result(job.result_payload or {})
            return {
                "job_id": job.pk,
                "state": "succeeded",
                "message": f"{len(erp_nrs)} passende Kundennummern in Microtech gefunden.",
                "result_count": len(erp_nrs),
                "erp_nrs": erp_nrs,
            }
        if job.kind == MicrotechGraphQLJob.Kind.CUSTOMER_READ:
            customer = self._microtech_customer_from_result(job.result_payload or {})
            if (job.context or {}).get("purpose") == "resolve":
                return {
                    "job_id": job.pk,
                    "state": "succeeded",
                    "message": f"{1 if customer else 0} passende Kunden in Microtech gefunden.",
                    "result_count": 1 if customer else 0,
                    "customers": [customer] if customer else [],
                }
            return {
                "job_id": job.pk,
                "state": "succeeded",
                "message": "Kundendaten aus Microtech geladen.",
                "data": customer,
            }
        return {"job_id": job.pk, "state": "failed", "error": "Ungültiger Microtech-Suchauftrag."}

    @staticmethod
    def _microtech_wait_message(status: str, operation: str) -> str:
        """Explain a running Microtech job without exposing internal job jargon."""
        if operation == "searchCustomers":
            if status == "queued":
                return "Die Suche in Microtech wird vorbereitet."
            if status in {"submitted", "running"}:
                return "Microtech prüft Kundennummer, E-Mail und Namen."
            return (
                "Microtech durchsucht die Kundendaten. Weitere passende Kunden "
                "werden automatisch ergänzt."
            )
        return "Die Kundendaten aus Microtech werden noch geladen."

    @staticmethod
    def _erp_numbers_from_dataset_result(result: dict[str, Any]) -> list[str]:
        erp_nrs: list[str] = []
        for record in result.get("records") or []:
            if not isinstance(record, dict):
                continue
            erp_nr = _to_str(record.get("AdrNr"))
            if erp_nr and erp_nr not in erp_nrs:
                erp_nrs.append(erp_nr)
        return erp_nrs

    @staticmethod
    def _erp_numbers_from_address_search_result(result: dict[str, Any]) -> list[str]:
        """Collect unique AdrNr values from a ``searchAddressRecords`` result."""
        erp_nrs: list[str] = []
        for dataset in result.get("datasets") or []:
            if not isinstance(dataset, dict):
                continue
            for record in dataset.get("records") or []:
                if not isinstance(record, dict):
                    continue
                erp_nr = _to_str(record.get("adrNr") or record.get("AdrNr"))
                if erp_nr and erp_nr not in erp_nrs:
                    erp_nrs.append(erp_nr)
        return erp_nrs

    @staticmethod
    def _microtech_customers_from_search_result(result: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize all customers from a direct poll or GraphQL webhook payload."""
        customers: list[dict[str, Any]] = []
        seen_erp_numbers: set[str] = set()
        for raw_customer in CustomerMergeSearchService._find_microtech_customers(result):
            customer = CustomerMergeSearchService._microtech_customer_from_result({"customer": raw_customer})
            erp_nr = _to_str((customer or {}).get("erp_nr"))
            if customer is not None and erp_nr and erp_nr not in seen_erp_numbers:
                customers.append(customer)
                seen_erp_numbers.add(erp_nr)
        return customers

    @staticmethod
    def _microtech_customer_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
        customer = CustomerMergeSearchService._find_microtech_customer(result)
        if not isinstance(customer, dict):
            return None

        addresses = []
        for address in customer.get("addresses") or []:
            if not isinstance(address, dict):
                continue
            contacts = [contact for contact in address.get("contacts") or [] if isinstance(contact, dict)]
            contact = next((item for item in contacts if item.get("isDefault")), contacts[0] if contacts else {})
            addresses.append(
                {
                    "ans_id": address.get("addressNumber"),
                    "ans_nr": address.get("addressSubNumber"),
                    "contact_numbers": [item["contactNumber"] for item in contacts if item.get("contactNumber") is not None],
                    "contacts": [
                        {
                            "asp_nr": item.get("contactNumber"),
                            "title": _to_str(item.get("salutation")),
                            "first_name": _to_str(item.get("firstName")),
                            "last_name": _to_str(item.get("lastName")),
                            "email": _to_str(item.get("email")),
                            "phone": _to_str(item.get("phone")),
                            "is_default": bool(item.get("isDefault")),
                        }
                        for item in contacts
                    ],
                    "name1": _to_str(address.get("name1")),
                    "name2": _to_str(address.get("name2")),
                    "street": _to_str(address.get("street")),
                    "postal_code": _to_str(address.get("zipCode")),
                    "city": _to_str(address.get("city")),
                    "country_code": _to_str(address.get("country")),
                    "email": _to_str(address.get("email")) or _to_str(contact.get("email")),
                    "firstName": _to_str(contact.get("firstName")),
                    "lastName": _to_str(contact.get("lastName")),
                    "phone": _to_str(address.get("phone")) or _to_str(contact.get("phone")),
                    "is_shipping": bool(address.get("isDefaultShipping")),
                    "is_invoice": bool(address.get("isDefaultBilling")),
                }
            )

        first_name = _to_str(customer.get("firstName"))
        last_name = _to_str(customer.get("lastName"))
        return {
            "erp_nr": _to_str(customer.get("customerNumber")),
            "name": _to_str(customer.get("name1")) or f"{first_name} {last_name}".strip(),
            "email": _to_str(customer.get("email")),
            "erp_id": customer.get("erpAddressNumber"),
            "status": _to_str(customer.get("source")),
            "addresses": addresses,
        }

    @staticmethod
    def _find_microtech_customer(payload: Any) -> dict[str, Any] | None:
        """Find a customer in a direct poll result or a GraphQL webhook payload."""
        if not isinstance(payload, dict):
            return None

        customer = payload.get("customer")
        if isinstance(customer, dict):
            return customer

        for value in payload.values():
            customer = CustomerMergeSearchService._find_microtech_customer(value)
            if customer is not None:
                return customer
        return None

    @staticmethod
    def _find_microtech_customers(payload: Any) -> list[dict[str, Any]]:
        """Find a customer list in a direct poll result or GraphQL webhook payload."""
        if not isinstance(payload, dict):
            return []

        customers = payload.get("customers")
        if isinstance(customers, list):
            return [customer for customer in customers if isinstance(customer, dict)]

        for value in payload.values():
            found = CustomerMergeSearchService._find_microtech_customers(value)
            if found:
                return found
        return []

    def search_django(self, erp_nr: str) -> dict[str, Any] | None:
        try:
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
            if not customer:
                return None
            addresses = list(
                customer.addresses.all().values(
                    "id", "erp_ans_id", "erp_ans_nr", "name1", "name2", "name3",
                    "street", "postal_code", "city", "country_code", "email",
                    "first_name", "last_name", "phone", "is_shipping", "is_invoice",
                    "api_id", "erp_nr", "erp_combined_id", "erp_asp_id", "erp_asp_nr",
                )
            )
            orders = list(
                customer.orders.all().values(
                    "id", "api_id", "order_number", "total_price", "order_state",
                    "purchase_date",
                )
            )
            return {
                "id": customer.id,
                "erp_nr": customer.erp_nr,
                "erp_id": customer.erp_id,
                "name": customer.name,
                "email": customer.email,
                "api_id": customer.api_id,
                "vat_id": customer.vat_id,
                "is_gross": customer.is_gross,
                "addresses": addresses,
                "orders": orders,
            }
        except Exception as exc:
            logger.error("Django search failed for {}: {}", erp_nr, exc)
            return {"error": str(exc)}

    def search_shopware(self, erp_nr: str) -> dict[str, Any] | None:
        try:
            from shopware.services import CustomerService
            service = CustomerService()
            response = service.get_by_customer_number(erp_nr)
            data = (response or {}).get("data", []) or []
            if not data:
                return None
            customer = data[0]
            attrs = _safe_attrs(customer)
            default_billing_id = _to_str(attrs.get("defaultBillingAddressId"))
            default_shipping_id = _to_str(attrs.get("defaultShippingAddressId"))
            addresses = []
            for addr in _safe_list(attrs.get("addresses")):
                a = _safe_attrs(addr)
                country = _safe_attrs(a.get("country")) if isinstance(a.get("country"), dict) else {}
                country_a = _safe_attrs(country) if country else {}
                address_id = _to_str(addr.get("id") or a.get("id"))
                addresses.append({
                    "id": address_id,
                    "firstName": a.get("firstName", ""),
                    "lastName": a.get("lastName", ""),
                    "company": a.get("company", ""),
                    "street": a.get("street", ""),
                    "zipcode": a.get("zipcode", ""),
                    "city": a.get("city", ""),
                    "countryIso": country_a.get("iso", ""),
                    "email": a.get("email") or attrs.get("email", ""),
                    "is_shipping": address_id == default_shipping_id,
                    "is_invoice": address_id == default_billing_id,
                })

            return {
                "id": customer.get("id") or attrs.get("id", ""),
                "customerNumber": attrs.get("customerNumber", ""),
                "email": attrs.get("email", ""),
                "firstName": attrs.get("firstName", ""),
                "lastName": attrs.get("lastName", ""),
                "company": attrs.get("company", ""),
                "updatedAt": attrs.get("updatedAt", ""),
                "lastLogin": attrs.get("lastLogin", ""),
                "addresses": addresses,
            }
        except Exception as exc:
            logger.error("Shopware search failed for {}: {}", erp_nr, exc)
            return {"error": str(exc)}

class CustomerMergeService(BaseService):
    """Merges two Django customers: moves orders/addresses from source to target."""

    def merge_customers(
        self,
        *,
        target_erp_nr: str,
        source_erp_nr: str,
        address_mapping: dict[str, str | None],
        merge_shopware_orders: bool = True,
    ) -> dict[str, Any]:
        target = Customer.objects.filter(erp_nr=target_erp_nr).first()
        source = Customer.objects.filter(erp_nr=source_erp_nr).first()
        if not target:
            raise ValueError(f"Ziel-Kunde {target_erp_nr} nicht in Django gefunden.")
        if not source:
            raise ValueError(f"Quell-Kunde {source_erp_nr} nicht in Django gefunden.")
        if target.pk == source.pk:
            raise ValueError("Ziel- und Quell-Kunde sind identisch.")

        log = []
        def _log(msg: str) -> None:
            logger.info("MERGE| {}", msg)
            log.append(msg)

        result = {
            "orders_moved": 0,
            "addresses_moved": 0,
            "shopware_orders_moved": 0,
            "password_source": None,
            "errors": [],
            "log": log,
        }

        _log(f"START: target={target_erp_nr} (pk={target.pk}, api_id={target.api_id}), "
             f"source={source_erp_nr} (pk={source.pk}, api_id={source.api_id})")
        _log(f"address_mapping={address_mapping}, merge_shopware_orders={merge_shopware_orders}")

        # Source addresses before merge
        src_addrs = list(source.addresses.all())
        tgt_addrs = list(target.addresses.all())
        _log(f"Source hat {len(src_addrs)} Adressen: {[(a.pk, a.street, a.postal_code, a.city) for a in src_addrs]}")
        _log(f"Target hat {len(tgt_addrs)} Adressen: {[(a.pk, a.street, a.postal_code, a.city) for a in tgt_addrs]}")

        # Determine which Shopware customer has the newer password
        password_winner = self._determine_password_winner(target, source)
        result["password_source"] = password_winner
        _log(f"Password winner: {password_winner}")

        # Move orders in Django
        source_orders = list(Order.objects.filter(customer=source).values_list("pk", flat=True))
        _log(f"Django Orders von source: {source_orders}")
        orders_moved = Order.objects.filter(customer=source).update(customer=target)
        result["orders_moved"] = orders_moved
        _log(f"Django Orders verschoben: {orders_moved}")

        # Move/merge addresses
        _log(f"Starte Adress-Merge mit mapping: {address_mapping}")
        result["addresses_moved"] = self._merge_addresses(
            target=target,
            source=source,
            address_mapping=address_mapping,
            _log=_log,
        )
        _log(f"Adressen verschoben/gemergt: {result['addresses_moved']}")

        # Check addresses after merge
        tgt_addrs_after = list(target.addresses.all())
        _log(f"Target Adressen nach Merge: {len(tgt_addrs_after)} — "
             f"{[(a.pk, a.street, a.postal_code, a.city, a.api_id) for a in tgt_addrs_after]}")
        src_addrs_after = list(source.addresses.all())
        _log(f"Source Adressen nach Merge (sollte leer/reduziert sein): {len(src_addrs_after)} — "
             f"{[(a.pk, a.street, a.postal_code, a.city) for a in src_addrs_after]}")

        # Move orders in Shopware
        if merge_shopware_orders and source.api_id and target.api_id:
            _log(f"Shopware Orders verschieben: source_sw={source.api_id} -> target_sw={target.api_id}")
            sw_moved, sw_errors = self._move_shopware_orders(
                target_sw_id=target.api_id,
                source_sw_id=source.api_id,
            )
            result["shopware_orders_moved"] = sw_moved
            result["errors"].extend(sw_errors)
            _log(f"Shopware Orders verschoben: {sw_moved}, Fehler: {sw_errors}")
        else:
            _log(f"Shopware Orders uebersprungen (merge_sw={merge_shopware_orders}, "
                 f"source.api_id={source.api_id}, target.api_id={target.api_id})")

        # Update Shopware password/email if needed
        if password_winner == "source" and source.api_id and target.api_id:
            _log("Kopiere Shopware-Login von source nach target")
            try:
                self._copy_shopware_login(
                    from_sw_id=source.api_id,
                    to_sw_id=target.api_id,
                )
                _log("Shopware-Login kopiert")
            except Exception as exc:
                result["errors"].append(f"Passwort-Kopie fehlgeschlagen: {exc}")
                _log(f"Shopware-Login Fehler: {exc}")

        _log("Merge abgeschlossen (Loeschen erfolgt manuell)")
        _log(f"FERTIG: result={result}")
        return result

    def _determine_password_winner(self, target: Customer, source: Customer) -> str:
        if not target.api_id or not source.api_id:
            return "target"
        try:
            from shopware.services import CustomerService
            service = CustomerService()
            target_data = service.get_by_id(target.api_id)
            source_data = service.get_by_id(source.api_id)

            def _get_timestamp(resp):
                data = (resp or {}).get("data", []) or []
                if not data:
                    return ""
                attrs = _safe_attrs(data[0])
                return attrs.get("updatedAt") or attrs.get("lastLogin") or ""

            target_ts = _get_timestamp(target_data)
            source_ts = _get_timestamp(source_data)
            return "source" if source_ts > target_ts else "target"
        except Exception as exc:
            logger.warning("Could not determine password winner: {}. Using target.", exc)
            return "target"

    def _merge_addresses(
        self,
        *,
        target: Customer,
        source: Customer,
        address_mapping: dict[str, str | None],
        _log=None,
    ) -> int:
        if _log is None:
            _log = lambda msg: logger.info("MERGE| {}", msg)

        moved = 0
        _log(f"_merge_addresses: mapping hat {len(address_mapping)} Eintraege")
        for src_addr_id_str, action in address_mapping.items():
            _log(f"  Mapping: src_addr_id={src_addr_id_str}, action={action!r}")
            try:
                src_addr = Address.objects.get(pk=int(src_addr_id_str), customer=source)
            except Address.DoesNotExist:
                _log(f"  -> src_addr {src_addr_id_str} nicht gefunden bei source (pk={source.pk})")
                continue

            _log(f"  -> src_addr gefunden: pk={src_addr.pk}, street={src_addr.street}, "
                 f"zip={src_addr.postal_code}, city={src_addr.city}, api_id={src_addr.api_id}")

            if action is None or action == "":
                _log("  -> action=verwerfen, uebersprungen")
                continue
            elif action == "new":
                old_customer_pk = src_addr.customer_id
                src_addr.customer = target
                src_addr.erp_combined_id = None
                src_addr.save()
                moved += 1
                _log(f"  -> als neue Adresse verschoben (customer {old_customer_pk} -> {target.pk})")
            else:
                try:
                    tgt_addr = Address.objects.get(pk=int(action), customer=target)
                    _log(f"  -> ueberschreibe target_addr pk={tgt_addr.pk} "
                         f"(street={tgt_addr.street}, zip={tgt_addr.postal_code})")
                    for field in (
                        "name1", "name2", "name3", "department", "street",
                        "postal_code", "city", "country_code", "email",
                        "title", "first_name", "last_name", "phone",
                    ):
                        setattr(tgt_addr, field, getattr(src_addr, field))
                    tgt_addr.save()
                    src_addr.delete()
                    moved += 1
                    _log(f"  -> target_addr aktualisiert, src_addr geloescht")
                except Address.DoesNotExist:
                    _log(f"  -> target_addr {action} nicht gefunden bei target (pk={target.pk})")
                    continue
        _log(f"_merge_addresses fertig: {moved} verschoben/gemergt")
        return moved

    def _move_shopware_orders(
        self, *, target_sw_id: str, source_sw_id: str
    ) -> tuple[int, list[str]]:
        moved = 0
        errors = []
        try:
            from shopware.services import Criteria, EqualsFilter, OrderService
            order_service = OrderService()
            criteria = Criteria(limit=500)
            criteria.associations["orderCustomer"] = Criteria()
            criteria.filter.append(
                EqualsFilter(field="orderCustomer.customerId", value=source_sw_id)
            )
            response = order_service.request_post("/search/order", payload=criteria)
            orders = (response or {}).get("data", []) or []

            for order in orders:
                order_id = order.get("id") or _safe_attrs(order).get("id")
                if not order_id:
                    continue
                oc = order.get("orderCustomer") or {}
                if isinstance(oc, dict):
                    oc_data = oc.get("data") or oc
                else:
                    oc_data = {}
                oc_attrs = _safe_attrs(oc_data)
                oc_id = oc_data.get("id") or oc_attrs.get("id")
                if not oc_id:
                    errors.append(f"Order {order_id}: orderCustomer ID nicht gefunden")
                    continue
                try:
                    order_service.request_patch(
                        f"/order-customer/{oc_id}",
                        payload={"customerId": target_sw_id},
                    )
                    moved += 1
                except Exception as exc:
                    errors.append(f"Order {order_id}: {exc}")
        except Exception as exc:
            errors.append(f"Shopware order migration failed: {exc}")
        return moved, errors

    def _copy_shopware_login(self, *, from_sw_id: str, to_sw_id: str) -> None:
        from shopware.services import CustomerService
        service = CustomerService()
        source_resp = service.get_by_id(from_sw_id)
        source_data = (source_resp or {}).get("data", []) or []
        if not source_data:
            raise ValueError("Source Shopware customer not found.")
        source_attrs = _safe_attrs(source_data[0])
        source_email = source_attrs.get("email", "")
        if source_email:
            service.update_customer(to_sw_id, {"email": source_email})
            logger.info("Shopware: copied email {} from {} to {}", source_email, from_sw_id, to_sw_id)


class CustomerDeleteService(BaseService):
    """Deletes a customer from one explicitly selected system."""

    def delete_django(self, erp_nr: str) -> dict[str, Any]:
        customer = Customer.objects.filter(erp_nr=erp_nr).first()
        if not customer:
            raise ValueError(f"Kunde {erp_nr} nicht in Django gefunden.")

        addr_count = customer.addresses.count()
        order_count = customer.orders.count()
        if order_count:
            raise ValueError(
                f"Kunde {erp_nr} hat noch {order_count} Bestellungen in Django. "
                f"Bitte zuerst Bestellungen verschieben (Merge)."
            )

        label = f"{customer.erp_nr} ({customer.name})"
        customer.delete()
        logger.info("Deleted Django customer {} ({} addresses)", label, addr_count)
        return {"deleted": label, "addresses_deleted": addr_count}

    def delete_shopware(self, erp_nr: str) -> dict[str, Any]:
        customer = Customer.objects.filter(erp_nr=erp_nr).first()
        sw_id = customer.api_id if customer else None

        if not sw_id:
            # Try to find directly in Shopware by customerNumber
            from shopware.services import CustomerService
            service = CustomerService()
            response = service.get_by_customer_number(erp_nr)
            data = (response or {}).get("data", []) or []
            if not data:
                raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden.")
            sw_id = _to_str(_safe_attrs(data[0]).get("id") or data[0].get("id"))

        if not sw_id:
            raise ValueError(f"Keine Shopware-ID fuer Kunde {erp_nr}.")

        from shopware.services import CustomerService
        service = CustomerService()
        service.request_delete(f"/customer/{sw_id}")

        # Clear api_id in Django if customer exists
        if customer and customer.api_id == sw_id:
            customer.api_id = ""
            customer.save(update_fields=["api_id", "updated_at"])

        logger.info("Deleted Shopware customer {} (sw_id={})", erp_nr, sw_id)
        return {"deleted_sw_id": sw_id}

    def delete_microtech(self, erp_nr: str) -> dict[str, Any]:
        erp_nr = _to_str(erp_nr)
        if not erp_nr:
            raise ValueError("AdrNr erforderlich.")

        from microtech.services import microtech_connection

        with microtech_connection() as client:
            result = client.delete_customer(erp_nr)
        if result.get("deleted") is not True:
            raise ValueError("Microtech hat die Kundenlöschung nicht bestätigt.")

        logger.info("Deleted Microtech customer AdrNr={}", erp_nr)
        return {"deleted_erp_nr": erp_nr}


class CustomerIdUpdateService(BaseService):
    """Updates local customer fields and external identifiers with scoped validation."""

    def update_django_name(self, customer_id: int, new_name: str) -> dict[str, str]:
        """Change only the display name stored in GC-Bridge."""
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_name = _to_str(new_name)
        if not new_name:
            raise ValueError("Name darf nicht leer sein.")
        if len(new_name) > 255:
            raise ValueError("Name darf höchstens 255 Zeichen lang sein.")

        old_name = customer.name
        customer.name = new_name
        customer.save(update_fields=["name", "updated_at"])
        logger.info("GC-Bridge customer name changed: customer={} {} -> {}", customer.pk, old_name, new_name)
        return {"old_name": old_name, "new_name": new_name}

    def update_shopware_customer_number(
        self, shopware_id: str, new_customer_number: str
    ) -> dict[str, Any]:
        """Change a Shopware customer number without requiring a local Django record."""
        shopware_id = _to_str(shopware_id)
        new_customer_number = _to_str(new_customer_number)
        if not shopware_id:
            raise ValueError("Shopware-ID darf nicht leer sein.")
        if not new_customer_number:
            raise ValueError("Kundennummer darf nicht leer sein.")

        from shopware.services import CustomerService

        service = CustomerService()
        response = service.get_by_customer_number(new_customer_number)
        for item in (response or {}).get("data", []) or []:
            item_id = _to_str(item.get("id") or _safe_attrs(item).get("id"))
            if item_id and item_id != shopware_id:
                raise ValueError(
                    f"Shopware: customerNumber {new_customer_number} wird bereits "
                    f"von Kunde {item_id} verwendet."
                )

        service.update_customer_number(shopware_id, new_customer_number)
        logger.info(
            "Shopware customer number changed: customer={} number={}",
            shopware_id,
            new_customer_number,
        )
        return {
            "shopware_id": shopware_id,
            "new_customer_number": new_customer_number,
        }

    def update_erp_nr(self, customer_id: int, new_erp_nr: str) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_erp_nr = _to_str(new_erp_nr)
        if not new_erp_nr:
            raise ValueError("ERP-Nummer darf nicht leer sein.")

        existing = Customer.objects.filter(erp_nr=new_erp_nr).exclude(pk=customer_id).first()
        if existing:
            raise ValueError(f"ERP-Nummer {new_erp_nr} wird bereits von Kunde {existing.name} verwendet.")

        old_erp_nr = customer.erp_nr
        steps = {"django": "ok", "shopware": "skipped", "microtech": "skipped"}

        # 1) Shopware
        if customer.api_id:
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                check = service.get_by_customer_number(new_erp_nr)
                check_data = (check or {}).get("data", []) or []
                for item in check_data:
                    item_id = item.get("id") or _safe_attrs(item).get("id", "")
                    if item_id and item_id != customer.api_id:
                        raise ValueError(
                            f"Shopware: customerNumber {new_erp_nr} wird bereits "
                            f"von Kunde {item_id} verwendet."
                        )
                service.update_customer_number(customer.api_id, new_erp_nr)
                steps["shopware"] = "ok"
            except ValueError:
                raise
            except Exception as exc:
                steps["shopware"] = str(exc)

        # 2) Microtech — GraphQL wrapper owns writes. There is no direct local
        # AdrNr rename via COM anymore, so we upsert the target number below.
        try:
            from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
            from microtech.services import microtech_connection

            customer.erp_nr = new_erp_nr
            with microtech_connection() as client:
                CustomerUpsertMicrotechService().upsert_customer(customer, erp=client)
            customer.erp_nr = old_erp_nr
            steps["microtech"] = "upserted"
        except Exception as exc:
            customer.erp_nr = old_erp_nr
            steps["microtech"] = str(exc)

        # 3) Django
        customer.erp_nr = new_erp_nr
        customer.save(update_fields=["erp_nr", "updated_at"])

        # 4) Microtech full upsert (updates default addresses after local save)
        if steps["microtech"] in ("upserted", "skipped"):
            try:
                self._django_to_microtech(new_erp_nr)
            except Exception as exc:
                steps["microtech_full_upsert"] = str(exc)

        logger.info("ERP-Nr changed: {} -> {} (customer {}) steps={}", old_erp_nr, new_erp_nr, customer.pk, steps)
        return {"old_erp_nr": old_erp_nr, "new_erp_nr": new_erp_nr, "steps": steps}

    def update_shopware_id(self, customer_id: int, new_api_id: str) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_api_id = _to_str(new_api_id)
        steps = {"django": "ok", "shopware": "validated"}

        if new_api_id:
            existing = Customer.objects.filter(api_id=new_api_id).exclude(pk=customer_id).first()
            if existing:
                raise ValueError(
                    f"Shopware-ID {new_api_id} wird bereits von Kunde {existing.erp_nr} verwendet."
                )
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                check = service.get_by_id(new_api_id)
                check_data = (check or {}).get("data", []) or []
                if not check_data:
                    raise ValueError(f"Shopware-Kunde mit ID {new_api_id} nicht gefunden.")
                # This is only a local association.  Shopware resource IDs and
                # customer numbers must never be changed by assigning a mapping.
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Shopware-Kunde konnte nicht validiert werden: {exc}") from exc

        old_api_id = customer.api_id
        customer.api_id = new_api_id
        customer.save(update_fields=["api_id", "updated_at"])

        logger.info("Shopware-ID changed: {} -> {} (customer {}) steps={}", old_api_id, new_api_id, customer.pk, steps)
        return {"old_api_id": old_api_id, "new_api_id": new_api_id, "steps": steps}

    def update_shopware_address_id(self, address_id: int, new_api_id: str) -> dict[str, Any]:
        """Assign a local address to an existing address of its Shopware customer."""
        address = Address.objects.select_related("customer").filter(pk=address_id).first()
        if not address:
            raise ValueError("Adresse nicht gefunden.")

        new_api_id = _to_str(new_api_id)
        if new_api_id:
            if not address.customer.api_id:
                raise ValueError("Die Shopware-ID des zugehörigen Kunden fehlt.")
            existing = Address.objects.filter(api_id=new_api_id).exclude(pk=address_id).first()
            if existing:
                raise ValueError("Diese Shopware-Adress-ID ist bereits lokal zugeordnet.")

            from shopware.services import CustomerService

            response = CustomerService().get_by_id(address.customer.api_id)
            customers = (response or {}).get("data", []) or []
            if not customers:
                raise ValueError("Der zugehörige Shopware-Kunde wurde nicht gefunden.")
            shopware_addresses = _safe_attrs(customers[0]).get("addresses") or []
            if new_api_id not in {_to_str(item.get("id")) for item in shopware_addresses}:
                raise ValueError("Die Shopware-Adress-ID gehört nicht zu diesem Kunden.")

        old_api_id = address.api_id
        address.api_id = new_api_id
        address.save(update_fields=["api_id", "updated_at"])
        logger.info("Shopware address mapping changed: {} -> {} (address {})", old_api_id, new_api_id, address.pk)
        return {"old_api_id": old_api_id, "new_api_id": new_api_id}

    def update_microtech_address_mapping(
        self,
        address_id: int,
        ans_nr: int,
        asp_nr: int | None,
    ) -> dict[str, Any]:
        """Map an existing Bridge address to a Microtech postal address/contact pair.

        The business keys are AdrNr, AnsNr and AnspNr.  The opaque Microtech
        IDs are deliberately cleared for a manual assignment so a later sync
        resolves the record through the selected business-key pair instead of
        restoring a previous opaque-ID association.
        """
        address = Address.objects.select_related("customer").filter(pk=address_id).first()
        if not address:
            raise ValueError("Adresse nicht gefunden.")
        if ans_nr < 0:
            raise ValueError("AnsNr darf nicht negativ sein.")
        if asp_nr is not None and asp_nr < 0:
            raise ValueError("AnspNr darf nicht negativ sein.")

        candidates = Address.objects.filter(customer=address.customer, erp_ans_nr=ans_nr).exclude(pk=address_id)
        duplicate = (
            candidates.filter(erp_asp_nr=asp_nr).first()
            if asp_nr is not None
            else candidates.filter(erp_asp_nr__isnull=True).first()
        )
        if duplicate:
            raise ValueError("Diese microtech-Anschrift/Ansprechpartner-Zuordnung ist bereits vergeben.")

        old_mapping = {"ans_nr": address.erp_ans_nr, "asp_nr": address.erp_asp_nr}
        address.erp_ans_nr = ans_nr
        address.erp_asp_nr = asp_nr
        address.erp_ans_id = None
        address.erp_asp_id = None
        address.erp_combined_id = None
        address.save(
            update_fields=[
                "erp_ans_nr",
                "erp_asp_nr",
                "erp_ans_id",
                "erp_asp_id",
                "erp_combined_id",
                "updated_at",
            ]
        )
        logger.info(
            "Microtech address mapping changed: {} -> AnsNr={} AnspNr={} (address {})",
            old_mapping,
            ans_nr,
            asp_nr,
            address.pk,
        )
        return {"old_mapping": old_mapping, "ans_nr": ans_nr, "asp_nr": asp_nr}


class CustomerSyncDirectionService(BaseService):
    """Syncs a single customer between two systems using existing services."""

    def sync(self, erp_nr: str, direction: str) -> dict[str, Any]:
        dispatch = {
            "shopware_to_django": self._shopware_to_django,
            "django_to_shopware": self._django_to_shopware,
            "microtech_to_django": self._microtech_to_django,
            "django_to_microtech": self._django_to_microtech,
        }
        handler = dispatch.get(direction)
        if not handler:
            raise ValueError(f"Unbekannte Richtung: {direction}")
        return handler(erp_nr)

    @staticmethod
    def _apply_shopware_address(
        address: Address,
        address_data: dict[str, Any],
        *,
        customer: Customer,
        default_billing_id: str,
        default_shipping_id: str,
    ) -> None:
        """Copy the displayable address fields from a verified SW6 address."""
        api_id = _to_str(address_data.get("id"))
        country = address_data.get("country") or {}
        if isinstance(country, dict):
            country = country.get("attributes") or country
        salutation = address_data.get("salutation") or {}
        if isinstance(salutation, dict):
            salutation = salutation.get("attributes") or salutation
        salutation_name = _to_str(
            salutation.get("displayName") if isinstance(salutation, dict) else ""
        )
        full_name = f"{_to_str(address_data.get('firstName'))} {_to_str(address_data.get('lastName'))}".strip()

        address.api_id = api_id
        address.title = salutation_name or address.title
        address.name1 = _to_str(address_data.get("company")) or full_name
        address.name2 = full_name if _to_str(address_data.get("company")) else ""
        address.department = _to_str(address_data.get("department"))
        address.street = _to_str(address_data.get("street"))
        address.postal_code = _to_str(address_data.get("zipcode"))
        address.city = _to_str(address_data.get("city"))
        address.country_code = _to_str(country.get("iso")) if isinstance(country, dict) else ""
        address.email = _to_str(address_data.get("email")) or customer.email
        address.first_name = _to_str(address_data.get("firstName"))
        address.last_name = _to_str(address_data.get("lastName"))
        address.phone = _to_str(address_data.get("phoneNumber"))
        address.is_invoice = api_id == default_billing_id
        address.is_shipping = api_id == default_shipping_id

    def import_shopware_address(self, *, erp_nr: str, shopware_address_id: str) -> dict[str, Any]:
        """Copy exactly one confirmed Shopware address into the matching local customer.

        This deliberately does not run the full customer import: a user clicking
        the comparison-arrow must not have unrelated local address mappings
        changed or removed as a side effect.
        """
        from orders.services.order_sync import _normalize_entity
        from shopware.services import CustomerService

        erp_nr = _to_str(erp_nr)
        requested_address_id = _to_str(shopware_address_id).lower()
        if not erp_nr:
            raise ValueError("ERP-Nummer erforderlich.")
        if not _UUID_RE.fullmatch(requested_address_id):
            raise ValueError("Eine gültige Shopware-Adress-ID ist erforderlich.")

        response = CustomerService().get_by_customer_number(erp_nr)
        data = (response or {}).get("data", []) or []
        if not data:
            raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden.")

        raw = _normalize_entity(data[0])
        shopware_customer_id = _to_str(raw.get("id")).lower()
        if not _UUID_RE.fullmatch(shopware_customer_id):
            raise ValueError("Shopware hat keine gültige Kunden-ID geliefert.")

        addresses_raw = raw.get("addresses") or []
        if isinstance(addresses_raw, dict):
            addresses_raw = addresses_raw.get("data") or []
        addresses_raw = _normalize_entity(addresses_raw) if isinstance(addresses_raw, list) else []
        address_data = next(
            (
                candidate for candidate in addresses_raw
                if isinstance(candidate, dict)
                and _to_str(candidate.get("id")).lower() == requested_address_id
            ),
            None,
        )
        if not address_data:
            raise ValueError("Die ausgewählte Adresse gehört nicht zum Shopware-Kunden.")

        default_billing_id = _to_str(raw.get("defaultBillingAddressId")).lower()
        default_shipping_id = _to_str(raw.get("defaultShippingAddressId")).lower()
        with transaction.atomic():
            customer = Customer.objects.select_for_update().filter(erp_nr=erp_nr).first()
            if not customer:
                raise ValueError(f"Kunde {erp_nr} nicht in Django gefunden.")
            if customer.api_id and customer.api_id.lower() != shopware_customer_id:
                raise ValueError(
                    "Die lokale Shopware-Kunden-ID stimmt nicht mit dem SW6-Kunden überein. "
                    "Bitte zuerst die Kunden-ID prüfen."
                )
            if Customer.objects.filter(api_id__iexact=shopware_customer_id).exclude(pk=customer.pk).exists():
                raise ValueError("Die Shopware-Kunden-ID ist bereits einem anderen Django-Kunden zugeordnet.")

            address = Address.objects.filter(
                customer=customer, api_id__iexact=requested_address_id,
            ).first()
            if not address:
                if Address.objects.filter(api_id__iexact=requested_address_id).exclude(customer=customer).exists():
                    raise ValueError("Die Shopware-Adresse ist bereits einem anderen Django-Kunden zugeordnet.")
                address = Address(customer=customer)

            if not customer.api_id:
                customer.api_id = shopware_customer_id
                customer.save(update_fields=["api_id", "updated_at"])

            self._apply_shopware_address(
                address,
                address_data,
                customer=customer,
                default_billing_id=default_billing_id,
                default_shipping_id=default_shipping_id,
            )
            address.save()
            if address.is_invoice:
                customer.addresses.exclude(pk=address.pk).update(is_invoice=False)
            if address.is_shipping:
                customer.addresses.exclude(pk=address.pk).update(is_shipping=False)

        logger.info(
            "Shopware->Django: copied address {} for customer {} as local address {}",
            requested_address_id,
            erp_nr,
            address.pk,
        )
        return {
            "message": "Shopware-Adresse nach Django übernommen.",
            "address_id": address.pk,
            "shopware_address_id": requested_address_id,
        }

    @staticmethod
    def _shopware_entity_id(response: Any) -> str:
        """Return the first entity ID from a Shopware search response."""
        data = response.get("data", response) if isinstance(response, dict) else response
        items = [data] if isinstance(data, dict) else _safe_list(data)
        for item in items:
            if not isinstance(item, dict):
                continue
            attrs = _safe_attrs(item)
            entity_id = _to_str(item.get("id")) or _to_str(attrs.get("id"))
            if entity_id:
                return entity_id
        return ""

    def _shopware_country_id(self, service: Any, country_code: str) -> str:
        """Resolve a Django ISO country code to Shopware's required country ID."""
        country_code = _to_str(country_code).upper()
        if not country_code:
            raise ValueError("Die Django-Adresse benötigt einen Ländercode für Shopware.")

        response = service.request_post(
            "/search/country",
            payload={
                "filter": [{"type": "equals", "field": "iso", "value": country_code}],
                "limit": 1,
            },
        )
        country_id = self._shopware_entity_id(response)
        if not country_id:
            raise ValueError(f"Das Land '{country_code}' ist in Shopware nicht vorhanden.")
        return country_id

    def _shopware_salutation_id(self, service: Any, customer_data: dict[str, Any]) -> str:
        """Use the customer's salutation, with Shopware's neutral one as fallback."""
        salutation_id = _to_str(customer_data.get("salutationId"))
        if not salutation_id:
            salutation = customer_data.get("salutation")
            if isinstance(salutation, dict):
                salutation_id = _to_str(salutation.get("id")) or _to_str(
                    _safe_attrs(salutation).get("id")
                )
        if salutation_id:
            return salutation_id

        response = service.request_post(
            "/search/salutation",
            payload={
                "filter": [
                    {"type": "equals", "field": "technicalName", "value": "not_specified"}
                ],
                "limit": 1,
            },
        )
        salutation_id = self._shopware_entity_id(response)
        if not salutation_id:
            raise ValueError("Shopware hat keine verwendbare Anrede für die Adresse.")
        return salutation_id

    @staticmethod
    def _shopware_address_payload(
        address: Address,
        *,
        country_id: str,
        salutation_id: str,
    ) -> dict[str, Any]:
        """Map one Django address to the Shopware customer-address payload."""
        payload: dict[str, Any] = {
            "firstName": address.first_name or address.name1 or ".",
            "lastName": address.last_name or address.name2 or ".",
            "street": address.street or ".",
            "zipcode": address.postal_code or ".",
            "city": address.city or ".",
            "company": address.name1 if address.name2 else "",
            "countryId": country_id,
            "salutationId": salutation_id,
        }
        if address.department:
            payload["department"] = address.department
        if address.email:
            payload["email"] = address.email
        if address.phone:
            payload["phoneNumber"] = address.phone
        return payload

    @staticmethod
    def _generated_shopware_address_id(address: Address) -> str:
        """Return a stable Shopware-compatible ID for one local address.

        Shopware accepts client-generated 32-character hexadecimal IDs.  A
        stable value makes the create operation safely retryable when SW6
        responds successfully without a JSON body.
        """
        return uuid5(
            NAMESPACE_URL,
            f"gc-bridge://shopware/customer-address/{address.customer_id}/{address.pk}",
        ).hex

    def export_django_address(self, *, erp_nr: str, django_address_id: int) -> dict[str, Any]:
        """Copy one confirmed Django address to its matching Shopware customer.

        This is deliberately the reverse of :meth:`import_shopware_address`:
        it changes only the selected address and writes it to SW6 immediately,
        instead of running the broader customer synchronisation.
        """
        from orders.services.order_sync import _normalize_entity
        from shopware.services import CustomerService

        erp_nr = _to_str(erp_nr)
        if not erp_nr:
            raise ValueError("ERP-Nummer erforderlich.")
        try:
            django_address_id = int(django_address_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Eine gültige Django-Adresse ist erforderlich.") from exc

        address = Address.objects.select_related("customer").filter(pk=django_address_id).first()
        if not address:
            raise ValueError("Django-Adresse nicht gefunden.")
        customer = address.customer
        if customer.erp_nr != erp_nr:
            raise ValueError("Die ausgewählte Adresse gehört nicht zu diesem Django-Kunden.")

        service = CustomerService()
        response = service.get_by_customer_number(erp_nr)
        data = (response or {}).get("data", []) or []
        if not data:
            raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden.")

        raw = _normalize_entity(data[0])
        shopware_customer_id = _to_str(raw.get("id")).lower()
        if not _UUID_RE.fullmatch(shopware_customer_id):
            raise ValueError("Shopware hat keine gültige Kunden-ID geliefert.")
        if customer.api_id and customer.api_id.lower() != shopware_customer_id:
            raise ValueError(
                "Die lokale Shopware-Kunden-ID stimmt nicht mit dem SW6-Kunden überein. "
                "Bitte zuerst die Kunden-ID prüfen."
            )
        if Customer.objects.filter(api_id__iexact=shopware_customer_id).exclude(pk=customer.pk).exists():
            raise ValueError("Die Shopware-Kunden-ID ist bereits einem anderen Django-Kunden zugeordnet.")

        addresses_raw = raw.get("addresses") or []
        if isinstance(addresses_raw, dict):
            addresses_raw = addresses_raw.get("data") or []
        addresses_raw = _normalize_entity(addresses_raw) if isinstance(addresses_raw, list) else []
        shopware_addresses = [item for item in addresses_raw if isinstance(item, dict)]
        shopware_by_id = {
            _to_str(item.get("id")).lower(): item
            for item in shopware_addresses
            if _to_str(item.get("id"))
        }
        location_key = f"{address.street}|{address.postal_code}".lower()
        shopware_by_location = {
            f"{_to_str(item.get('street'))}|{_to_str(item.get('zipcode'))}".lower(): item
            for item in shopware_addresses
            if _to_str(item.get("street")) or _to_str(item.get("zipcode"))
        }
        if address.api_id and address.api_id.lower() not in shopware_by_id:
            raise ValueError(
                "Die lokale SW6-Adress-ID gehört nicht zu diesem Shopware-Kunden. "
                "Bitte zuerst die Adresszuordnung prüfen."
            )
        shopware_address = shopware_by_id.get(address.api_id.lower()) if address.api_id else None
        if not shopware_address and location_key != "|":
            shopware_address = shopware_by_location.get(location_key)

        country_id = self._shopware_country_id(service, address.country_code)
        salutation_id = self._shopware_salutation_id(service, raw)
        payload = self._shopware_address_payload(
            address,
            country_id=country_id,
            salutation_id=salutation_id,
        )

        if shopware_address:
            shopware_address_id = _to_str(shopware_address.get("id"))
            service.request_patch(f"/customer-address/{shopware_address_id}", payload=payload)
            created = False
        else:
            shopware_address_id = self._generated_shopware_address_id(address)
            payload["id"] = shopware_address_id
            payload["customerId"] = shopware_customer_id
            service.request_post("/customer-address", payload=payload)
            created = True

        default_updates: dict[str, str] = {}
        if address.is_invoice or not _to_str(raw.get("defaultBillingAddressId")):
            default_updates["defaultBillingAddressId"] = shopware_address_id
        if address.is_shipping or not _to_str(raw.get("defaultShippingAddressId")):
            default_updates["defaultShippingAddressId"] = shopware_address_id
        if default_updates:
            service.update_customer(shopware_customer_id, default_updates)

        with transaction.atomic():
            locked_customer = Customer.objects.select_for_update().filter(pk=customer.pk).first()
            locked_address = Address.objects.select_for_update().filter(
                pk=django_address_id, customer=locked_customer
            ).first()
            if not locked_customer or not locked_address:
                raise ValueError("Django-Kunde oder Adresse wurde zwischenzeitlich geändert.")
            if not locked_customer.api_id:
                locked_customer.api_id = shopware_customer_id
                locked_customer.save(update_fields=["api_id", "updated_at"])
            if locked_address.api_id != shopware_address_id:
                locked_address.api_id = shopware_address_id
                locked_address.save(update_fields=["api_id", "updated_at"])

        logger.info(
            "Django->Shopware: copied local address {} for customer {} as Shopware address {}",
            django_address_id,
            erp_nr,
            shopware_address_id,
        )
        return {
            "message": "Django-Adresse nach Shopware übernommen.",
            "address_id": django_address_id,
            "shopware_address_id": shopware_address_id,
            "created": created,
        }

    def set_address_default(
        self,
        *,
        erp_nr: str,
        django_address_id: int,
        role: str,
    ) -> dict[str, Any]:
        """Set one fully mapped address as billing or shipping in all systems.

        Django is the mapping hub: its address must carry both the Shopware
        address ID and the Microtech address sub-number.  This prevents a
        default selection from being applied to unrelated addresses.
        """
        from orders.services.order_sync import _normalize_entity
        from microtech.services import microtech_connection
        from shopware.services import CustomerService

        erp_nr = _to_str(erp_nr)
        if not erp_nr:
            raise ValueError("ERP-Nummer erforderlich.")
        try:
            django_address_id = int(django_address_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Eine gültige Django-Adresse ist erforderlich.") from exc

        role_fields = {
            "billing": ("is_invoice", "defaultBillingAddressId", "defaultBillingAddressNumber"),
            "shipping": ("is_shipping", "defaultShippingAddressId", "defaultShippingAddressNumber"),
        }
        if role not in role_fields:
            raise ValueError("Rolle muss 'billing' oder 'shipping' sein.")
        django_field, shopware_field, microtech_field = role_fields[role]

        address = Address.objects.select_related("customer").filter(pk=django_address_id).first()
        if not address:
            raise ValueError("Django-Adresse nicht gefunden.")
        customer = address.customer
        if customer.erp_nr != erp_nr:
            raise ValueError("Die ausgewählte Adresse gehört nicht zu diesem Django-Kunden.")
        shopware_address_id = _to_str(address.api_id).lower()
        if not _UUID_RE.fullmatch(shopware_address_id):
            raise ValueError(
                "Die Adresse ist noch nicht lückenlos mit Shopware verknüpft. "
                "Bitte zuerst die SW6-Adresszuordnung herstellen."
            )
        try:
            microtech_address_number = int(address.erp_ans_nr)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Die Adresse ist noch nicht lückenlos mit Microtech verknüpft. "
                "Bitte zuerst die Microtech-Anschrift zuordnen."
            ) from exc
        if microtech_address_number < 0:
            raise ValueError("Die Microtech-AnsNr darf nicht negativ sein.")

        shopware_service = CustomerService()
        response = shopware_service.get_by_customer_number(erp_nr)
        data = (response or {}).get("data", []) or []
        if not data:
            raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden.")
        shopware_customer = _normalize_entity(data[0])
        shopware_customer_id = _to_str(shopware_customer.get("id")).lower()
        if not _UUID_RE.fullmatch(shopware_customer_id):
            raise ValueError("Shopware hat keine gültige Kunden-ID geliefert.")
        if customer.api_id and customer.api_id.lower() != shopware_customer_id:
            raise ValueError(
                "Die lokale Shopware-Kunden-ID stimmt nicht mit dem SW6-Kunden überein. "
                "Bitte zuerst die Kunden-ID prüfen."
            )

        addresses_raw = shopware_customer.get("addresses") or []
        if isinstance(addresses_raw, dict):
            addresses_raw = addresses_raw.get("data") or []
        addresses_raw = _normalize_entity(addresses_raw) if isinstance(addresses_raw, list) else []
        shopware_address_ids = {
            _to_str(item.get("id")).lower()
            for item in addresses_raw
            if isinstance(item, dict) and _to_str(item.get("id"))
        }
        if shopware_address_id not in shopware_address_ids:
            raise ValueError("Die SW6-Adresse gehört nicht zu diesem Shopware-Kunden.")

        # Both remote writes are performed before Django changes its local
        # flags. A failed remote write therefore cannot make the comparison
        # screen claim a fully synchronized default assignment.
        shopware_service.update_customer(
            shopware_customer_id,
            {shopware_field: shopware_address_id},
        )
        with microtech_connection() as microtech_client:
            microtech_client.update_customer(
                erp_nr,
                {microtech_field: microtech_address_number},
            )

        with transaction.atomic():
            locked_customer = Customer.objects.select_for_update().filter(pk=customer.pk).first()
            if not locked_customer:
                raise ValueError("Django-Kunde wurde zwischenzeitlich geändert.")
            locked_addresses = locked_customer.addresses
            locked_addresses.update(**{django_field: False})
            # One Microtech postal address can have multiple contact persons.
            # All local rows for that Anschrift mirror its shared default role.
            locked_addresses.filter(erp_ans_nr=microtech_address_number).update(**{django_field: True})

        logger.info(
            "Address default synchronized: customer={} role={} django_address={} shopware_address={} microtech_ans_nr={}",
            erp_nr,
            role,
            django_address_id,
            shopware_address_id,
            microtech_address_number,
        )
        return {
            "message": (
                "Rechnungsadresse" if role == "billing" else "Lieferadresse"
            ) + " in SW6, Django und Microtech gesetzt.",
            "role": role,
            "address_id": django_address_id,
            "shopware_address_id": shopware_address_id,
            "microtech_address_number": microtech_address_number,
        }

    def _shopware_to_django(self, erp_nr: str) -> dict[str, Any]:
        """Import customer + addresses from Shopware into Django."""
        from shopware.services import CustomerService

        service = CustomerService()
        response = service.get_by_customer_number(erp_nr)
        data = (response or {}).get("data", []) or []
        if not data:
            raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden.")

        from orders.services.order_sync import _normalize_entity, _to_str as _os_to_str

        raw = _normalize_entity(data[0])
        customer_id = _os_to_str(raw.get("id"))
        customer_number = _os_to_str(raw.get("customerNumber")) or erp_nr

        customer = Customer.objects.filter(erp_nr=customer_number).first()
        if not customer and customer_id:
            customer = Customer.objects.filter(api_id=customer_id).first()
        if not customer:
            customer = Customer(erp_nr=customer_number)

        vat_ids = raw.get("vatIds") or []
        first = _os_to_str(raw.get("firstName"))
        last = _os_to_str(raw.get("lastName"))
        company = _os_to_str(raw.get("company"))
        if "company" in raw:
            customer.company = company
        customer.name = company or f"{first} {last}".strip() or customer.name
        customer.email = _os_to_str(raw.get("email")) or customer.email
        customer.api_id = customer_id or customer.api_id
        customer_group = raw.get("group") or {}
        customer.is_gross = bool(customer_group.get("displayGross", True))
        customer.shopware_customer_group = _os_to_str(customer_group.get("name")) or customer.shopware_customer_group
        customer.vat_id = _os_to_str(vat_ids[0]) if vat_ids else customer.vat_id
        customer.save()

        # Upsert addresses
        addresses_raw = raw.get("addresses") or []
        if isinstance(addresses_raw, dict):
            addresses_raw = addresses_raw.get("data") or []
        addresses_raw = _normalize_entity(addresses_raw) if isinstance(addresses_raw, list) else []

        default_billing_id = _os_to_str(raw.get("defaultBillingAddressId"))
        default_shipping_id = _os_to_str(raw.get("defaultShippingAddressId"))
        addr_count = 0
        seen_addr_ids: set[int] = set()

        for addr_data in addresses_raw:
            if not isinstance(addr_data, dict):
                continue
            api_id = _os_to_str(addr_data.get("id"))
            if not api_id:
                continue

            # Match by api_id first, then by street+zip to avoid duplicates
            addr = Address.objects.filter(customer=customer, api_id=api_id).first()
            if not addr:
                sw_street = _os_to_str(addr_data.get("street"))
                sw_zip = _os_to_str(addr_data.get("zipcode"))
                if sw_street and sw_zip:
                    addr = Address.objects.filter(
                        customer=customer, street=sw_street, postal_code=sw_zip,
                    ).exclude(id__in=seen_addr_ids).first()
            if not addr:
                addr = Address(customer=customer)

            addr.api_id = api_id
            self._apply_shopware_address(
                addr,
                addr_data,
                customer=customer,
                default_billing_id=default_billing_id,
                default_shipping_id=default_shipping_id,
            )
            addr.save()
            seen_addr_ids.add(addr.pk)
            addr_count += 1

        # Remove Django addresses that no longer exist in Shopware
        if seen_addr_ids:
            orphans = Address.objects.filter(customer=customer).exclude(id__in=seen_addr_ids)
            orphan_count = orphans.count()
            if orphan_count:
                orphans.delete()
                logger.info("Shopware->Django: {} removed {} orphan addresses", erp_nr, orphan_count)

        logger.info("Shopware->Django: {} synced ({} addresses)", erp_nr, addr_count)
        return {"message": f"Kunde aus Shopware importiert ({addr_count} Adressen)"}

    def _django_to_shopware(self, erp_nr: str) -> dict[str, Any]:
        """Sync Django customer + addresses to Shopware (upsert)."""
        from orders.services.order_sync import _normalize_entity

        customer = Customer.objects.filter(erp_nr=erp_nr).first()
        if not customer:
            self._shopware_to_django(erp_nr)
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
            if not customer:
                raise ValueError(f"Kunde {erp_nr} weder in Django noch in Shopware gefunden.")

        from shopware.services import CustomerService
        service = CustomerService()

        # Auto-link: if no api_id, try to find Shopware customer by customerNumber
        if not customer.api_id:
            response = service.get_by_customer_number(erp_nr)
            data = (response or {}).get("data", []) or []
            if not data:
                raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden — kann nicht verknuepfen.")
            sw_id = _to_str(_safe_attrs(data[0]).get("id") or data[0].get("id"))
            if sw_id:
                customer.api_id = sw_id
                customer.save(update_fields=["api_id", "updated_at"])
                logger.info("Django->Shopware: auto-linked {} -> {}", erp_nr, sw_id)

        # Fetch existing Shopware addresses to match and get countryId/salutationId
        sw_response = service.get_by_id(customer.api_id)
        sw_data = (sw_response or {}).get("data", []) or []
        sw_raw = _normalize_entity(sw_data[0]) if sw_data else {}
        sw_addresses_raw = sw_raw.get("addresses") or []
        if isinstance(sw_addresses_raw, dict):
            sw_addresses_raw = sw_addresses_raw.get("data") or []
        if isinstance(sw_addresses_raw, list):
            sw_addresses_raw = [_normalize_entity(a) if isinstance(a, dict) else a for a in sw_addresses_raw]

        # Build lookup: api_id -> sw_address, street+zip -> sw_address
        sw_by_id: dict[str, dict] = {}
        sw_by_location: dict[str, dict] = {}
        default_country_id = ""
        default_salutation_id = ""
        for swa in sw_addresses_raw:
            if not isinstance(swa, dict):
                continue
            swa_id = _to_str(swa.get("id"))
            if swa_id:
                sw_by_id[swa_id] = swa
            loc_key = f"{_to_str(swa.get('street'))}|{_to_str(swa.get('zipcode'))}".lower()
            if loc_key and loc_key != "|":
                sw_by_location[loc_key] = swa
            if not default_country_id:
                default_country_id = _to_str(swa.get("countryId"))
            if not default_salutation_id:
                default_salutation_id = _to_str(swa.get("salutationId"))

        if not default_salutation_id:
            default_salutation_id = _to_str(sw_raw.get("salutationId"))

        # Upsert Django addresses into Shopware
        django_addresses = list(customer.addresses.all())
        addr_count = 0
        for addr in django_addresses:
            sw_match = None
            if addr.api_id:
                sw_match = sw_by_id.get(addr.api_id)
            if not sw_match:
                loc_key = f"{addr.street}|{addr.postal_code}".lower()
                sw_match = sw_by_location.get(loc_key)

            # Build payload
            payload: dict[str, Any] = {
                "firstName": addr.first_name or addr.name1 or ".",
                "lastName": addr.last_name or addr.name2 or ".",
                "street": addr.street or ".",
                "zipcode": addr.postal_code or ".",
                "city": addr.city or ".",
                "company": addr.name1 if addr.name2 else "",
            }
            if addr.phone:
                payload["phoneNumber"] = addr.phone

            if sw_match:
                # Update existing Shopware address
                sw_addr_id = _to_str(sw_match.get("id"))
                if sw_addr_id:
                    try:
                        service.request_patch(f"/customer-address/{sw_addr_id}", payload=payload)
                        if not addr.api_id:
                            addr.api_id = sw_addr_id
                            addr.save(update_fields=["api_id", "updated_at"])
                        addr_count += 1
                    except Exception as exc:
                        logger.warning("Django->Shopware: failed to update address {}: {}", sw_addr_id, exc)
            else:
                # Create new address in Shopware
                payload["customerId"] = customer.api_id
                payload["countryId"] = default_country_id
                payload["salutationId"] = default_salutation_id
                try:
                    result = service.request_post("/customer-address", payload=payload)
                    # Extract new address ID from response
                    new_id = ""
                    if isinstance(result, dict):
                        new_id = _to_str(result.get("data", {}).get("id") if isinstance(result.get("data"), dict) else result.get("id"))
                    if new_id:
                        addr.api_id = new_id
                        addr.save(update_fields=["api_id", "updated_at"])
                    addr_count += 1
                except Exception as exc:
                    logger.warning("Django->Shopware: failed to create address for {}: {}", erp_nr, exc)

        service.update_customer_number(customer.api_id, erp_nr)
        logger.info("Django->Shopware: {} synced ({} addresses)", erp_nr, addr_count)
        return {"message": f"Shopware verknuepft ({addr_count} Adressen synchronisiert)"}

    def _microtech_to_django(self, erp_nr: str) -> dict[str, Any]:
        """Import customer + addresses from Microtech into Django."""
        from customer.services.customer_sync import CustomerSyncService
        svc = CustomerSyncService()
        customer = svc.sync_from_microtech(erp_nr)
        addr_count = customer.addresses.count()
        logger.info("Microtech->Django: {} synced ({} addresses)", erp_nr, addr_count)
        return {"message": f"Kunde aus Microtech importiert ({addr_count} Adressen)"}

    def _django_to_microtech(self, erp_nr: str) -> dict[str, Any]:
        """Push customer + ALL addresses from Django to Microtech."""
        customer = Customer.objects.filter(erp_nr=erp_nr).first()
        if not customer:
            # Auto-create from Microtech first
            self._microtech_to_django(erp_nr)
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
            if not customer:
                raise ValueError(f"Kunde {erp_nr} weder in Django noch in Microtech gefunden.")

        all_addresses = list(customer.addresses.all())
        if not all_addresses:
            raise ValueError(f"Kunde {erp_nr} hat keine Adressen in Django.")

        from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
        from microtech.services import microtech_connection

        svc = CustomerUpsertMicrotechService()
        with microtech_connection() as client:
            shipping = customer.shipping_address or all_addresses[0]
            billing = customer.billing_address or shipping
            result = svc.upsert_customer(
                customer,
                shipping_address=shipping,
                billing_address=billing,
                erp=client,
            )
            address_number = int(result.erp_nr)
            for addr in all_addresses:
                if addr.pk in {shipping.pk, billing.pk}:
                    continue
                svc._upsert_postal_address_graphql(
                    client=client,
                    address_number=address_number,
                    address=addr,
                    # The pair selected above is the only default pair.
                    is_shipping=False,
                    is_invoice=False,
                    na1_mode="auto",
                    na1_static_value="",
                    known_address_sub_numbers=result.known_address_sub_numbers,
                    include_email=bool(addr.is_shipping),
                )

        addr_count = len(all_addresses)
        msg = f"Kunde nach Microtech uebertragen ({addr_count} Adressen)"
        if result.is_new_customer:
            msg += " [NEU]"
        logger.info("Django->Microtech: {} upserted ({} addresses)", erp_nr, addr_count)
        return {"message": msg}


class ShopwareMergeError(ValueError):
    """Safe plugin/transport failure; never includes a raw upstream response."""

    def __init__(self, message: str, *, code: str, status: int = 502, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.uncertain = uncertain


class ShopwareCustomerMergeService(BaseService):
    """Delegate the complete SW6 merge to the transactional Shopware plugin.

    Django never reads/writes a password hash and never falls back to a series
    of customer/address/order API mutations. The selected target ID survives.
    """

    ENDPOINT = "/_action/gc-customer-merge"
    VERIFIED_FIELDS = ("credentials", "addresses", "orders", "defaults", "identity")
    # Request and return only displayable business fields, never password hashes,
    # recovery/registration tokens or arbitrary extension payloads.
    CUSTOMER_COMPARISON_FIELDS = (
        "id", "customerNumber", "email", "firstName", "lastName", "company", "title",
        "salutationId", "vatIds", "accountType", "birthday", "active", "guest",
        "lastLogin", "firstLogin", "createdAt", "groupId", "salesChannelId", "languageId",
        "lastPaymentMethodId", "requestedGroupId", "affiliateCode", "campaignCode",
        "doubleOptInRegistration", "doubleOptInEmailSentDate", "doubleOptInConfirmDate",
        "defaultBillingAddressId", "defaultShippingAddressId",
    )
    ADDRESS_COMPARISON_FIELDS = (
        "id", "customerId", "salutationId", "title", "firstName", "lastName", "company",
        "department", "street", "additionalAddressLine1", "additionalAddressLine2",
        "zipcode", "city", "countryId", "countryStateId", "phoneNumber",
    )

    def _comparison_snapshot(self, payload: dict) -> dict:
        """Read both customers and every address without truncating large collections."""
        from shopware.services import CustomerService

        service = CustomerService()
        ids = [payload["sourceId"], payload["targetId"]]
        try:
            response = service._request_with_retry("request_post", "/search/customer", payload={
                "ids": ids, "limit": 2,
                "includes": {"customer": list(self.CUSTOMER_COMPARISON_FIELDS)},
            })
            customers = {}
            for item in response["data"]:
                attrs = _safe_attrs(item)
                customer = {field: attrs.get(field) for field in self.CUSTOMER_COMPARISON_FIELDS}
                customer["id"] = self._id(item.get("id") or attrs.get("id"), "Kunde")
                customers[customer["id"]] = {**customer, "addresses": []}
            if set(customers) != set(ids):
                raise ValueError("Unvollständige Kundenansicht")
            page, seen = 1, set()
            while True:
                response = service._request_with_retry("request_post", "/search/customer-address", payload={
                    "filter": [{"type": "equalsAny", "field": "customerId", "value": ids}],
                    "limit": 100, "page": page, "total-count-mode": 1,
                    "sort": [{"field": "id", "order": "ASC"}],
                    "associations": {"country": {}, "countryState": {}, "salutation": {}},
                    "includes": {
                        "customer_address": [*self.ADDRESS_COMPARISON_FIELDS, "country", "countryState", "salutation"],
                        "country": ["iso", "name"], "country_state": ["shortCode", "name"],
                        "salutation": ["displayName"],
                    },
                })
                rows, total = response["data"], response["total"]
                if not isinstance(rows, list) or type(total) is not int or total < 0:
                    raise ValueError("Unvollständige Adressansicht")
                for item in rows:
                    attrs = _safe_attrs(item)
                    address = {field: attrs.get(field) for field in self.ADDRESS_COMPARISON_FIELDS}
                    address["id"] = self._id(item.get("id") or attrs.get("id"), "Adresse")
                    if address["id"] in seen or address["customerId"] not in customers:
                        raise ValueError("Abweichende Adressansicht")
                    seen.add(address["id"])
                    for association, field in (("country", "name"), ("countryState", "name"), ("salutation", "displayName")):
                        value = attrs.get(association)
                        address[association] = _to_str(_safe_attrs(value).get(field)) if isinstance(value, dict) else ""
                    customers[address["customerId"]]["addresses"].append(address)
                if len(seen) == total:
                    break
                if not rows or len(seen) > total:
                    raise ValueError("Unvollständige Adressansicht")
                page += 1
            return {"source": customers[ids[0]], "target": customers[ids[1]]}
        except Exception:
            raise ShopwareMergeError(
                "Die Kunden- und Adressfelder konnten nicht vollständig aus Shopware geladen werden. "
                "Bitte die Vorschau erneut laden. Es wurde kein Merge gestartet.",
                code="GC_MERGE_COMPARISON_UNAVAILABLE",
            ) from None

    @staticmethod
    def _id(value: Any, label: str) -> str:
        value = _to_str(value).lower()
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ValueError(f"{label} muss eine gültige 32-stellige Shopware-ID sein.")
        return value

    def _payload(
        self, *, keep_sw_id: str, delete_sw_id: str,
        default_billing_address_id: str = "", default_shipping_address_id: str = "",
    ) -> dict[str, str]:
        target = self._id(keep_sw_id, "Zielkunde")
        source = self._id(delete_sw_id, "Quellkunde")
        if target == source:
            raise ValueError("Quell- und Zielkunde müssen unterschiedlich sein.")
        payload = {"sourceId": source, "targetId": target}
        for key, value in (
            ("defaultBillingAddressId", default_billing_address_id),
            ("defaultShippingAddressId", default_shipping_address_id),
        ):
            if value:
                payload[key] = self._id(value, "Standardadresse")
        return payload

    @staticmethod
    def _upstream_error(data: Any, status: int, *, uncertain: bool) -> ShopwareMergeError:
        errors = data.get("errors") if isinstance(data, dict) else None
        if isinstance(errors, list):
            for error in errors:
                if not isinstance(error, dict):
                    continue
                code, detail = error.get("code"), error.get("detail")
                if (
                    isinstance(code, str) and re.fullmatch(r"GC_MERGE_[A-Z0-9_]+", code)
                    and isinstance(detail, str) and 0 < len(detail) <= 2000
                ):
                    return ShopwareMergeError(
                        detail, code=code, status=status,
                        uncertain=uncertain and (status >= 500 or code in (
                            "GC_MERGE_OPERATION_CONFLICT", "GC_MERGE_FAILED",
                        )),
                    )
        if status in (401, 403):
            return ShopwareMergeError(
                "Keine Berechtigung für das Shopware-Merge-Plugin. Bitte API-Anmeldung und Merge-ACL prüfen.",
                code="GC_MERGE_ACCESS_DENIED", status=403, uncertain=uncertain,
            )
        if status == 404:
            return ShopwareMergeError(
                "Das Shopware-Plugin GecoCustomerMerge ist nicht erreichbar. Installation und Aktivierung prüfen. "
                "Es wird kein ungesicherter Ersatz-Merge ausgeführt.",
                code="GC_MERGE_PLUGIN_UNAVAILABLE", status=503, uncertain=uncertain,
            )
        return ShopwareMergeError(
            "Shopware hat kein bestätigtes Merge-Ergebnis geliefert. "
            "Bitte den Vorgangsstatus prüfen; nicht mit einer neuen Vorgangs-ID erneut starten."
            if uncertain else "Die Shopware-Merge-Vorschau ist nicht verfügbar. Es wurde kein Merge gestartet.",
            code="GC_MERGE_STATUS_UNKNOWN" if uncertain else "GC_MERGE_PREVIEW_UNAVAILABLE",
            status=502, uncertain=uncertain,
        )

    def _request(self, action: str, *, payload: dict | None = None, operation_id: str = "") -> dict:
        from shopware.services import CustomerService

        service = CustomerService()
        path = f"{self.ENDPOINT}/{action}"
        uncertain = action != "preview"
        try:
            # Bypass the generic wrapper's response/payload debug logging.
            # The existing authenticated transport also retains HTTP error causes.
            if action == "status":
                data = service._request_with_retry("request_get", f"{path}/{operation_id}")
            else:
                data = service._request_with_retry("request_post", path, payload=payload)
        except Exception as exc:
            cause = exc
            for _ in range(6):
                response = getattr(cause, "response", None)
                if response is not None:
                    status = getattr(response, "status_code", 502)
                    try:
                        detail = response.json()
                    except Exception:
                        detail = None
                    raise self._upstream_error(
                        detail, status if isinstance(status, int) else 502, uncertain=uncertain
                    ) from None
                cause = getattr(cause, "__cause__", None)
                if cause is None:
                    break
            # Do not log/return str(exc): external errors may contain credentials.
            raise self._upstream_error(None, 502, uncertain=uncertain) from None
        if not isinstance(data, dict) or data.get("errors"):
            raise self._upstream_error(data, 502, uncertain=uncertain)
        return data

    def _validate_result(
        self, data: dict, *, payload: dict | None = None, operation_id: str = "", preview: bool = False,
    ) -> dict:
        try:
            source = self._id(data.get("sourceId"), "Plugin-Quellkunde")
            target = self._id(data.get("targetId"), "Plugin-Zielkunde")
            credential_source = self._id(data.get("credentialSourceId"), "Login-Quelle")
            if source == target or credential_source not in (source, target):
                raise ValueError("Ungültige Login-Quelle.")
            if payload and (source != payload["sourceId"] or target != payload["targetId"]):
                raise ValueError("Plugin hat Quell- oder Zielkunde vertauscht.")
            copied = data.get("credentialsCopied")
            if not isinstance(copied, bool) or copied != (credential_source == source):
                raise ValueError("Unbestätigte Credential-Übertragung.")
            clean = {
                "sourceId": source, "targetId": target,
                "credentialSourceId": credential_source, "credentialsCopied": copied,
            }
            for field in ("addressesMoved", "ordersMoved"):
                count = data.get(field)
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ValueError("Ungültige Anzahl.")
                clean[field] = count
            for field in ("defaultBillingAddressId", "defaultShippingAddressId"):
                clean[field] = self._id(data.get(field), "Standardadresse")
                if payload and payload.get(field) and clean[field] != payload[field]:
                    raise ValueError("Abweichende Standardadresse.")
            if preview:
                token = data.get("previewToken")
                if not isinstance(token, str) or not token or len(token) > 4096:
                    raise ValueError("Vorschau-Bestätigung fehlt.")
                clean["previewToken"] = token
            else:
                if data.get("status") != "merged" or data.get("sourceDeleted") is not True:
                    raise ValueError("Merge nicht bestätigt.")
                if data.get("operationId") != operation_id:
                    raise ValueError("Abweichende Vorgangs-ID.")
                verified = data.get("verified")
                if not isinstance(verified, dict) or any(verified.get(f) is not True for f in self.VERIFIED_FIELDS):
                    raise ValueError("Merge-Prüfung unvollständig.")
                last_login = data.get("lastLogin")
                if last_login is not None and (not isinstance(last_login, str) or len(last_login) > 80):
                    raise ValueError("Ungültiger Login-Zeitpunkt.")
                clean.update({
                    "status": "merged", "sourceDeleted": True, "operationId": operation_id,
                    "lastLogin": last_login,
                    "verified": {field: True for field in self.VERIFIED_FIELDS},
                })
            # Explicit allowlist: unexpected password/hash fields are never forwarded.
            return clean
        except ValueError:
            raise self._upstream_error(None, 502, uncertain=not preview) from None

    def preview(self, *, include_comparison: bool = False, **selection) -> dict[str, Any]:
        payload = self._payload(**selection)
        before = self._comparison_snapshot(payload) if include_comparison else None
        data = self._request("preview", payload=payload)
        result = self._validate_result(data, payload=payload, preview=True)
        if include_comparison:
            # Bracket the signed plugin preview with fresh reads. Never show stale
            # search-cache fields alongside a newer, authoritative merge plan.
            after = self._comparison_snapshot(payload)
            if before != after or len(after["source"]["addresses"]) != result["addressesMoved"]:
                raise ShopwareMergeError(
                    "Die Kundendaten haben sich während der Vorschau geändert. Bitte die Vorschau erneut laden.",
                    code="GC_MERGE_PREVIEW_STALE", status=409,
                )
            result["comparison"] = after
        return result

    def merge(self, *, operation_id: str, preview_token: str, **selection) -> dict[str, Any]:
        payload = self._payload(**selection)
        operation_id = self._id(operation_id, "Vorgangs-ID")
        if not isinstance(preview_token, str) or not preview_token or len(preview_token) > 4096:
            raise ValueError("Eine aktuelle, bestätigte Shopware-Vorschau ist erforderlich.")
        payload.update({"operationId": operation_id, "previewToken": preview_token})
        data = self._request("execute", payload=payload)
        return self._validate_result(data, payload=payload, operation_id=operation_id)

    def status(self, *, operation_id: str) -> dict[str, Any]:
        operation_id = self._id(operation_id, "Vorgangs-ID")
        data = self._request("status", operation_id=operation_id)
        if data.get("status") == "not_found" and data.get("operationId") == operation_id:
            return {"status": "not_found", "operationId": operation_id}
        return self._validate_result(data, operation_id=operation_id)

    def cleanup_django_source_after_merge(
        self, *, source_sw_id: str, target_sw_id: str,
    ) -> dict[str, Any]:
        """Remove the local source account after the plugin confirmed its deletion.

        Local orders and addresses are assigned to the surviving local target
        first. The source customer is only deleted once it has neither, mirroring
        the confirmed Shopware merge without losing local address references.
        """
        source_sw_id = self._id(source_sw_id, "Shopware-Quellkunde")
        target_sw_id = self._id(target_sw_id, "Shopware-Zielkunde")
        if source_sw_id == target_sw_id:
            raise ShopwareMergeError(
                "Die lokale Bereinigung konnte nicht zugeordnet werden: Quelle und Ziel sind identisch.",
                code="GC_MERGE_DJANGO_CLEANUP_INVALID", status=409,
            )

        with transaction.atomic():
            source_customers = list(
                Customer.objects.select_for_update().filter(api_id__iexact=source_sw_id)
            )
            if len(source_customers) > 1:
                raise ShopwareMergeError(
                    "Die lokale Bereinigung wurde nicht ausgeführt: Die Shopware-Quell-ID ist mehrfach in Django hinterlegt.",
                    code="GC_MERGE_DJANGO_CLEANUP_AMBIGUOUS", status=409,
                )
            if not source_customers:
                return {"status": "already_removed", "orders_moved": 0, "addresses_moved": 0}

            target_customers = list(
                Customer.objects.select_for_update().filter(api_id__iexact=target_sw_id)
            )
            if len(target_customers) != 1:
                raise ShopwareMergeError(
                    "Der Shopware-Merge ist abgeschlossen, aber der lokale Zielkunde ist nicht eindeutig. "
                    "Der Django-Quellkunde wurde deshalb nicht gelöscht.",
                    code="GC_MERGE_DJANGO_CLEANUP_TARGET_MISSING", status=409,
                )

            source = source_customers[0]
            target = target_customers[0]
            if source.pk == target.pk:
                raise ShopwareMergeError(
                    "Die lokale Bereinigung konnte nicht zugeordnet werden: Quelle und Ziel zeigen auf denselben Django-Kunden.",
                    code="GC_MERGE_DJANGO_CLEANUP_INVALID", status=409,
                )

            source_addresses = list(source.addresses.select_for_update())
            target_addresses = list(target.addresses.select_for_update())
            target_shopware_address_ids = {
                address.api_id.lower() for address in target_addresses if address.api_id
            }
            target_microtech_keys = {
                (address.erp_ans_id, address.erp_asp_id)
                for address in target_addresses
                if address.erp_ans_id is not None
            }
            for address in source_addresses:
                if address.api_id and address.api_id.lower() in target_shopware_address_ids:
                    raise ShopwareMergeError(
                        "Die lokale Bereinigung wurde nicht ausgeführt: Eine SW6-Adresse ist bereits beim Django-Zielkunden vorhanden.",
                        code="GC_MERGE_DJANGO_CLEANUP_ADDRESS_CONFLICT", status=409,
                    )
                microtech_key = (address.erp_ans_id, address.erp_asp_id)
                if address.erp_ans_id is not None and microtech_key in target_microtech_keys:
                    raise ShopwareMergeError(
                        "Die lokale Bereinigung wurde nicht ausgeführt: Eine Microtech-Adresszuordnung würde beim Zielkunden doppelt sein.",
                        code="GC_MERGE_DJANGO_CLEANUP_ADDRESS_CONFLICT", status=409,
                    )

            source_addresses_query = Address.objects.filter(customer=source)
            # The Shopware target keeps its own defaults. Do not turn a source
            # default into a second local standard address while moving it.
            if any(address.is_invoice for address in target_addresses):
                source_addresses_query.update(is_invoice=False)
            if any(address.is_shipping for address in target_addresses):
                source_addresses_query.update(is_shipping=False)
            addresses_moved = source_addresses_query.update(customer=target)
            orders_moved = Order.objects.filter(customer=source).update(customer=target)
            source_label = f"{source.erp_nr} ({source.name})"
            source.delete()

        logger.info(
            "SW-MERGE-DJANGO-CLEANUP| moved {} addresses and {} orders from source {} to {}; source removed",
            addresses_moved,
            orders_moved,
            source_label,
            target.erp_nr,
        )
        return {
            "status": "deleted",
            "source": source_label,
            "target_erp_nr": target.erp_nr,
            "orders_moved": orders_moved,
            "addresses_moved": addresses_moved,
        }


class ShopwareCustomerAddressService(BaseService):
    """Deletes explicitly selected non-default Shopware customer addresses."""

    def delete_addresses(self, *, customer_id: str, address_ids: list[str]) -> dict[str, int]:
        customer_id = _to_str(customer_id)
        selected_ids = {_to_str(address_id) for address_id in address_ids if _to_str(address_id)}
        if not customer_id:
            raise ValueError("Shopware-Kunden-ID erforderlich.")
        if not selected_ids:
            raise ValueError("Keine Shopware-Adressen ausgewaehlt.")

        from shopware.services import CustomerService

        service = CustomerService()
        response = service.get_by_id(customer_id)
        data = (response or {}).get("data", []) or []
        if not data:
            raise ValueError(f"Shopware-Kunde {customer_id} nicht gefunden.")

        attrs = _safe_attrs(data[0])
        available_ids = {
            _to_str(address.get("id") or _safe_attrs(address).get("id"))
            for address in _safe_list(attrs.get("addresses"))
        }
        unknown_ids = sorted(selected_ids - available_ids)
        if unknown_ids:
            raise ValueError(
                "Die gewaehlten Adressen gehoeren nicht zum Shopware-Kunden: "
                + ", ".join(unknown_ids)
            )

        default_ids = {
            _to_str(attrs.get("defaultBillingAddressId")),
            _to_str(attrs.get("defaultShippingAddressId")),
        }
        default_ids.discard("")
        protected_ids = sorted(selected_ids & default_ids)
        if protected_ids:
            raise ValueError(
                "Standard-Liefer- oder Rechnungsadressen koennen erst geloescht werden, "
                "wenn vorher eine andere Adresse als Standard gesetzt wurde: "
                + ", ".join(protected_ids)
            )

        for address_id in sorted(selected_ids):
            service.request_delete(f"/customer-address/{address_id}")
        logger.info(
            "SW-ADDRESS-DELETE| {} address(es) deleted for customer {}",
            len(selected_ids),
            customer_id,
        )
        return {"deleted": len(selected_ids)}
