from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings
from loguru import logger

from core.services import BaseService


class GraphQLMicrotechError(RuntimeError):
    pass


class GraphQLMicrotechTimeout(TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class MicrotechGraphQLConfig:
    url: str
    request_timeout: float = 30.0
    poll_timeout: float = 180.0
    poll_interval: float = 2.0

    @classmethod
    def from_settings(cls) -> "MicrotechGraphQLConfig":
        url = (getattr(settings, "MICROTECH_GRAPHQL_URL", "") or "").strip()
        if not url:
            raise ValueError("Missing MICROTECH_GRAPHQL_URL setting.")
        return cls(
            url=url,
            request_timeout=float(getattr(settings, "MICROTECH_GRAPHQL_REQUEST_TIMEOUT", 30.0)),
            poll_timeout=float(getattr(settings, "MICROTECH_GRAPHQL_POLL_TIMEOUT", 180.0)),
            poll_interval=float(getattr(settings, "MICROTECH_GRAPHQL_POLL_INTERVAL", 2.0)),
        )


class MicrotechGraphQLClientService(BaseService):
    """HTTP GraphQL client for the external Microtech wrapper."""

    TERMINAL_SUCCESS = {"DONE", "SUCCEEDED", "SUCCESS"}
    TERMINAL_FAILED = {"FAILED", "ERROR", "CANCELLED"}

    def __init__(self, *, config: MicrotechGraphQLConfig | None = None) -> None:
        self.config = config or MicrotechGraphQLConfig.from_settings()

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.post(
            self.config.url,
            json={"query": query, "variables": variables or {}},
            headers={"Content-Type": "application/json"},
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") or []
        if errors:
            message = "; ".join(str((item or {}).get("message") or item) for item in errors)
            raise GraphQLMicrotechError(message)
        data = payload.get("data")
        if data is None:
            raise GraphQLMicrotechError("GraphQL response did not contain data.")
        return data

    def health(self) -> str:
        data = self.execute("query { health }")
        return str(data.get("health") or "")

    def ping(self) -> str:
        data = self.execute("mutation { ping }")
        return str(data.get("ping") or "")

    def request_dataset_records(self, input_data: dict[str, Any]) -> dict[str, Any]:
        data = self.execute(
            """
            mutation RequestDatasetRecords($input: DatasetReadInput!) {
              requestDatasetRecords(input: $input) {
                accepted
                jobId
                status
                message
                retryAfterSeconds
              }
            }
            """,
            {"input": input_data},
        )
        return self._accepted(data, "requestDatasetRecords")

    def dataset_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            query DatasetJob($jobId: ID!) {
              datasetJob(jobId: $jobId) {
                jobId
                status
                message
                errorMessage
                dataset
                indexField
                recordCount
                returnedCount
                hasMore
                nextCursor
                records
                fieldMeta {
                  fieldName
                  label
                  fieldType
                  isCalcField
                  canAccess
                }
              }
            }
            """,
            {"jobId": job_id},
        )
        return data.get("datasetJob") or {}

    def poll_dataset_records(self, input_data: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        accepted = self.request_dataset_records(input_data)
        return self.poll_job(
            job_id=str(accepted["jobId"]),
            query_job=self.dataset_job,
            retry_after=accepted.get("retryAfterSeconds"),
            timeout=timeout,
        )

    def submit_dataset_job(self, input_data: dict[str, Any]) -> tuple[str, float]:
        """Submit dataset job without blocking. Returns (job_id, retry_after_seconds)."""
        accepted = self.request_dataset_records(input_data)
        return str(accepted["jobId"]), float(accepted.get("retryAfterSeconds") or self.config.poll_interval)

    def check_dataset_job_once(self, job_id: str) -> dict[str, Any] | None:
        """Single non-blocking poll. Returns job result if DONE, None if still pending, raises on failure."""
        job = self.dataset_job(job_id)
        status = str(job.get("status") or "").upper()
        if status in self.TERMINAL_SUCCESS:
            return job
        if status in self.TERMINAL_FAILED:
            raise GraphQLMicrotechError(
                str(job.get("errorMessage") or job.get("message") or "Microtech GraphQL job failed.")
            )
        return None

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            mutation CancelJob($jobId: ID!) {
              cancelJob(jobId: $jobId) {
                accepted
                jobId
                status
                message
              }
            }
            """,
            {"jobId": job_id},
        )
        return self._accepted(data, "cancelJob")

    def delete_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            mutation DeleteJob($jobId: ID!) {
              deleteJob(jobId: $jobId) {
                accepted
                jobId
                status
                message
              }
            }
            """,
            {"jobId": job_id},
        )
        return self._accepted(data, "deleteJob")

    def microtech_version(self) -> dict[str, Any]:
        data = self.execute(
            """
            mutation {
              microtechVersion { accepted jobId status message retryAfterSeconds }
            }
            """
        )
        accepted = self._accepted(data, "microtechVersion")
        job = self.poll_job(
            job_id=str(accepted["jobId"]),
            query_job=self.microtech_job,
            retry_after=accepted.get("retryAfterSeconds"),
        )
        return job.get("result") or {}

    def microtech_connection(self, *, timeout: float | None = None) -> dict[str, Any]:
        data = self.execute(
            """
            mutation {
              microtechConnection { accepted jobId status message retryAfterSeconds }
            }
            """
        )
        accepted = self._accepted(data, "microtechConnection")
        job = self.poll_job(
            job_id=str(accepted["jobId"]),
            query_job=self.microtech_job,
            retry_after=accepted.get("retryAfterSeconds"),
            timeout=timeout,
        )
        return job.get("result") or {}

    def switch_microtech_mandant(self, mandant: str, *, timeout: float | None = None) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation SwitchMicrotechMandant($mandant: String!) {
              switchMicrotechMandant(mandant: $mandant) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "switchMicrotechMandant",
            {"mandant": str(mandant).strip()},
        )
        job = self.poll_job(
            job_id=str(accepted["jobId"]),
            query_job=self.microtech_job,
            retry_after=accepted.get("retryAfterSeconds"),
            timeout=timeout,
        )
        return job.get("result") or {}

    def microtech_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            query MicrotechJob($jobId: ID!) {
              microtechJob(jobId: $jobId) {
                jobId status message result errorMessage
              }
            }
            """,
            {"jobId": job_id},
        )
        return data.get("microtechJob") or {}

    def request_product(self, erp_number: str) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation RequestProduct($erpNumber: String!) {
              requestProduct(erpNumber: $erpNumber) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestProduct",
            {"erpNumber": erp_number},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.product_job, retry_after=accepted.get("retryAfterSeconds"))

    def submit_request_products(
        self,
        *,
        erp_numbers: Sequence[str] | None = None,
        include_images: bool = True,
    ) -> tuple[str, float]:
        """Submit fixed product list read without blocking. Returns (job_id, retry_after_seconds)."""
        cleaned = [str(erp_nr).strip() for erp_nr in (erp_numbers or []) if str(erp_nr).strip()]
        accepted = self._mutation_with_job(
            """
            mutation RequestProducts($erpNumbers: [String!], $includeImages: Boolean!) {
              requestProducts(erpNumbers: $erpNumbers, includeImages: $includeImages) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestProducts",
            {"erpNumbers": cleaned or None, "includeImages": bool(include_images)},
        )
        return str(accepted["jobId"]), float(accepted.get("retryAfterSeconds") or self.config.poll_interval)

    def product_list_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            query ProductListJob($jobId: ID!) {
              productListJob(jobId: $jobId) {
                jobId status message errorMessage
                products {
                  erpNumber name description descriptionShort isActive factor unit
                  minPurchase purchaseUnit sortOrder taxKey taxRate
                  customsTariffNumber weightGrossKg weightNetKg price
                  rebateQuantity rebatePrice specialPrice specialStartDate specialEndDate
                  warehouseNumber stock storageLocation deleted images source
                }
              }
            }
            """,
            {"jobId": job_id},
        )
        return data.get("productListJob") or {}

    def update_product(self, erp_number: str, input_data: dict[str, Any]) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateProduct($erpNumber: String!, $input: UpdateProductInput!) {
              updateProduct(erpNumber: $erpNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateProduct",
            {"erpNumber": erp_number, "input": input_data},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.product_job, retry_after=accepted.get("retryAfterSeconds"))

    def submit_update_product(self, erp_number: str, input_data: dict[str, Any]) -> tuple[str, float]:
        """Submit product update without blocking. Returns (job_id, retry_after_seconds)."""
        accepted = self._mutation_with_job(
            """
            mutation UpdateProduct($erpNumber: String!, $input: UpdateProductInput!) {
              updateProduct(erpNumber: $erpNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateProduct",
            {"erpNumber": erp_number, "input": input_data},
        )
        return str(accepted["jobId"]), float(accepted.get("retryAfterSeconds") or self.config.poll_interval)

    def product_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            query ProductJob($jobId: ID!) {
              productJob(jobId: $jobId) {
                jobId status message deleted errorMessage
                product {
                  erpNumber name description descriptionShort isActive factor unit
                  minPurchase purchaseUnit sortOrder taxKey taxRate
                  customsTariffNumber weightGrossKg weightNetKg price
                  rebateQuantity rebatePrice specialPrice specialStartDate specialEndDate
                  warehouseNumber stock storageLocation deleted images source
                }
              }
            }
            """,
            {"jobId": job_id},
        )
        return data.get("productJob") or {}

    def request_customer(self, customer_number: str) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation RequestCustomer($customerNumber: String!) {
              requestCustomer(customerNumber: $customerNumber) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestCustomer",
            {"customerNumber": customer_number},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def create_customer(self, customer_number: str, input_data: dict[str, Any]) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation CreateCustomer($customerNumber: String!, $input: CustomerInput!) {
              createCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def update_customer(self, customer_number: str, input_data: dict[str, Any]) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateCustomer($customerNumber: String!, $input: CustomerInput!) {
              updateCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def create_postal_address(self, address_number: int, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._postal_address_mutation("createPostalAddress", address_number, None, input_data)

    def update_postal_address(self, address_number: int, address_sub_number: int, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._postal_address_mutation("updatePostalAddress", address_number, address_sub_number, input_data)

    def delete_postal_address(self, address_number: int, address_sub_number: int) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation DeletePostalAddress($addressNumber: Int!, $addressSubNumber: Int!) {
              deletePostalAddress(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "deletePostalAddress",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def create_contact_person(self, address_number: int, address_sub_number: int, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._contact_person_mutation("createContactPerson", address_number, address_sub_number, None, input_data)

    def update_contact_person(
        self,
        address_number: int,
        address_sub_number: int,
        contact_number: int,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        return self._contact_person_mutation("updateContactPerson", address_number, address_sub_number, contact_number, input_data)

    def delete_contact_person(self, address_number: int, address_sub_number: int, contact_number: int) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation DeleteContactPerson($addressNumber: Int!, $addressSubNumber: Int!, $contactNumber: Int!) {
              deleteContactPerson(
                addressNumber: $addressNumber,
                addressSubNumber: $addressSubNumber,
                contactNumber: $contactNumber
              ) { accepted jobId status message retryAfterSeconds }
            }
            """,
            "deleteContactPerson",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "contactNumber": contact_number},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def request_vorgang(self, beleg_nr: str) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation RequestVorgang($belegNr: String!) {
              requestVorgang(belegNr: $belegNr) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestVorgang",
            {"belegNr": beleg_nr},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.vorgang_job, retry_after=accepted.get("retryAfterSeconds"))

    def create_vorgang(self, input_data: dict[str, Any]) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation CreateVorgang($input: CreateVorgangInput!) {
              createVorgang(input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createVorgang",
            {"input": input_data},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.vorgang_job, retry_after=accepted.get("retryAfterSeconds"))

    def update_vorgang(self, beleg_nr: str, input_data: dict[str, Any]) -> dict[str, Any]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateVorgang($belegNr: String!, $input: UpdateVorgangInput!) {
              updateVorgang(belegNr: $belegNr, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateVorgang",
            {"belegNr": beleg_nr, "input": input_data},
        )
        return self.poll_job(str(accepted["jobId"]), query_job=self.vorgang_job, retry_after=accepted.get("retryAfterSeconds"))

    # ------------------------------------------------------------------
    # Non-blocking submit methods — return (job_id, retry_after) immediately
    # without polling. Mirror the blocking twins above 1:1.
    # ------------------------------------------------------------------

    def _submit_accepted(self, accepted: dict[str, Any]) -> tuple[str, float]:
        return str(accepted["jobId"]), float(accepted.get("retryAfterSeconds") or self.config.poll_interval)

    def submit_request_customer(self, customer_number: str) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation RequestCustomer($customerNumber: String!) {
              requestCustomer(customerNumber: $customerNumber) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestCustomer",
            {"customerNumber": customer_number},
        )
        return self._submit_accepted(accepted)

    def submit_create_customer(self, customer_number: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreateCustomer($customerNumber: String!, $input: CustomerInput!) {
              createCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_customer(self, customer_number: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateCustomer($customerNumber: String!, $input: CustomerInput!) {
              updateCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_upsert_customer(self, customer_number: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpsertCustomer($customerNumber: String!, $input: CustomerInput!) {
              upsertCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "upsertCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_create_postal_address(self, address_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreatePostalAddress($addressNumber: Int!, $input: PostalAddressInput!) {
              createPostalAddress(addressNumber: $addressNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createPostalAddress",
            {"addressNumber": address_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_postal_address(self, address_number: int, address_sub_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdatePostalAddress($addressNumber: Int!, $addressSubNumber: Int!, $input: PostalAddressInput!) {
              updatePostalAddress(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updatePostalAddress",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_create_contact_person(self, address_number: int, address_sub_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreateContactPerson($addressNumber: Int!, $addressSubNumber: Int!, $input: ContactPersonInput!) {
              createContactPerson(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createContactPerson",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_contact_person(self, address_number: int, address_sub_number: int, contact_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateContactPerson($addressNumber: Int!, $addressSubNumber: Int!, $contactNumber: Int!, $input: ContactPersonInput!) {
              updateContactPerson(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, contactNumber: $contactNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateContactPerson",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "contactNumber": contact_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_request_vorgang(self, beleg_nr: str) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation RequestVorgang($belegNr: String!) {
              requestVorgang(belegNr: $belegNr) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestVorgang",
            {"belegNr": beleg_nr},
        )
        return self._submit_accepted(accepted)

    def submit_create_vorgang(self, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreateVorgang($input: CreateVorgangInput!) {
              createVorgang(input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createVorgang",
            {"input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_vorgang(self, beleg_nr: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateVorgang($belegNr: String!, $input: UpdateVorgangInput!) {
              updateVorgang(belegNr: $belegNr, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateVorgang",
            {"belegNr": beleg_nr, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def customer_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            query CustomerJob($jobId: ID!) {
              customerJob(jobId: $jobId) {
                jobId status message errorMessage
                customer {
                  customerNumber erpAddressNumber salutation firstName lastName
                  name1 name2 name3 street zipCode city email phone department country
                  defaultShippingAddressNumber defaultBillingAddressNumber source
                  addresses {
                    addressNumber addressSubNumber isDefaultShipping isDefaultBilling
                    name1 name2 name3 street zipCode city email phone department country
                    contacts {
                      addressNumber addressSubNumber contactNumber isDefault salutation
                      firstName lastName displayName department email phone
                    }
                  }
                }
                postalAddress {
                  addressNumber addressSubNumber isDefaultShipping isDefaultBilling
                  name1 street zipCode city email phone country
                  contacts { contactNumber firstName lastName email phone }
                }
                contactPerson {
                  addressNumber addressSubNumber contactNumber isDefault salutation
                  firstName lastName displayName department email phone
                }
              }
            }
            """,
            {"jobId": job_id},
        )
        return data.get("customerJob") or {}

    def vorgang_job(self, job_id: str) -> dict[str, Any]:
        data = self.execute(
            """
            query VorgangJob($jobId: ID!) {
              vorgangJob(jobId: $jobId) {
                jobId status message errorMessage
                vorgang {
                  belegNr vorgangArt erpAddressNumber orderNumber date description
                  netto brutto currency status source
                  positions { belegNr positionNr erpNumber name quantity unit unitPrice totalPrice taxKey discountRate }
                }
              }
            }
            """,
            {"jobId": job_id},
        )
        return data.get("vorgangJob") or {}

    def poll_job(
        self,
        job_id: str,
        *,
        query_job,
        retry_after: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        timeout = self.config.poll_timeout if timeout is None else timeout
        interval = self._coerce_interval(retry_after)
        max_interval = max(self.config.poll_interval * 5, interval)
        deadline = time.monotonic() + timeout

        while True:
            job = query_job(job_id)
            status = str(job.get("status") or "").upper()
            if status in self.TERMINAL_SUCCESS:
                return job
            if status in self.TERMINAL_FAILED:
                raise GraphQLMicrotechError(str(job.get("errorMessage") or job.get("message") or "Microtech GraphQL job failed."))
            if time.monotonic() >= deadline:
                raise GraphQLMicrotechTimeout(f"Microtech GraphQL job {job_id} did not finish within {timeout}s.")
            time.sleep(interval)
            interval = min(interval * 1.5, max_interval)

    def _mutation_with_job(self, query: str, field: str, variables: dict[str, Any]) -> dict[str, Any]:
        data = self.execute(query, variables)
        return self._accepted(data, field)

    @staticmethod
    def _accepted(data: dict[str, Any], field: str) -> dict[str, Any]:
        accepted = data.get(field) or {}
        if not accepted.get("accepted"):
            raise GraphQLMicrotechError(str(accepted.get("message") or f"GraphQL mutation {field} was not accepted."))
        if not accepted.get("jobId"):
            raise GraphQLMicrotechError(f"GraphQL mutation {field} did not return a jobId.")
        return accepted

    def _postal_address_mutation(
        self,
        field: str,
        address_number: int,
        address_sub_number: int | None,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        if address_sub_number is None:
            query = """
            mutation CreatePostalAddress($addressNumber: Int!, $input: PostalAddressInput!) {
              createPostalAddress(addressNumber: $addressNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """
            variables = {"addressNumber": address_number, "input": input_data}
        else:
            query = """
            mutation UpdatePostalAddress($addressNumber: Int!, $addressSubNumber: Int!, $input: PostalAddressInput!) {
              updatePostalAddress(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """
            variables = {"addressNumber": address_number, "addressSubNumber": address_sub_number, "input": input_data}
        accepted = self._mutation_with_job(query, field, variables)
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def _contact_person_mutation(
        self,
        field: str,
        address_number: int,
        address_sub_number: int,
        contact_number: int | None,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        if contact_number is None:
            query = """
            mutation CreateContactPerson($addressNumber: Int!, $addressSubNumber: Int!, $input: ContactPersonInput!) {
              createContactPerson(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """
            variables = {"addressNumber": address_number, "addressSubNumber": address_sub_number, "input": input_data}
        else:
            query = """
            mutation UpdateContactPerson(
              $addressNumber: Int!, $addressSubNumber: Int!, $contactNumber: Int!, $input: ContactPersonInput!
            ) {
              updateContactPerson(
                addressNumber: $addressNumber, addressSubNumber: $addressSubNumber,
                contactNumber: $contactNumber, input: $input
              ) { accepted jobId status message retryAfterSeconds }
            }
            """
            variables = {
                "addressNumber": address_number,
                "addressSubNumber": address_sub_number,
                "contactNumber": contact_number,
                "input": input_data,
            }
        accepted = self._mutation_with_job(query, field, variables)
        return self.poll_job(str(accepted["jobId"]), query_job=self.customer_job, retry_after=accepted.get("retryAfterSeconds"))

    def _coerce_interval(self, value: Any) -> float:
        try:
            interval = float(value)
        except (TypeError, ValueError):
            interval = self.config.poll_interval
        return max(self.config.poll_interval, interval, 0.1)


@contextmanager
def microtech_graphql_connection():
    client = MicrotechGraphQLClientService()
    logger.debug("Using Microtech GraphQL endpoint {}.", client.config.url)
    yield client
