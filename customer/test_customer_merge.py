import json
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from customer.services.customer_merge import (
    CustomerDeleteService,
    CustomerIdUpdateService,
    CustomerMergeSearchService,
    ShopwareCustomerAddressService,
    ShopwareCustomerMergeService,
    ShopwareMergeError,
    _has_wildcard,
    _split_terms,
    _wildcard_segments,
)


def _sw_customer(
    cid,
    number,
    email="",
    *,
    last_login="",
    first_name="",
    last_name="",
    company="",
    addresses=None,
):
    return {
        "data": [
            {
                "id": cid,
                "attributes": {
                    "customerNumber": number,
                    "email": email,
                    "lastLogin": last_login,
                    "firstName": first_name,
                    "lastName": last_name,
                    "company": company,
                    "addresses": addresses or [],
                },
            }
        ]
    }


class CustomerIdUpdateServiceTest(SimpleTestCase):
    @patch("customer.services.customer_merge.Customer")
    @patch("shopware.services.CustomerService")
    def test_customer_shopware_mapping_never_changes_remote_customer_number(
        self, customer_service, customer_model
    ):
        customer = MagicMock(pk=7, erp_nr="10001", api_id="")
        by_pk = MagicMock()
        by_pk.first.return_value = customer
        duplicates = MagicMock()
        duplicates.exclude.return_value.first.return_value = None
        customer_model.objects.filter.side_effect = [by_pk, duplicates]
        customer_service.return_value.get_by_id.return_value = {"data": [{"id": "a" * 32}]}

        result = CustomerIdUpdateService().update_shopware_id(7, "a" * 32)

        self.assertEqual(result["new_api_id"], "a" * 32)
        self.assertEqual(customer.api_id, "a" * 32)
        customer.save.assert_called_once_with(update_fields=["api_id", "updated_at"])
        customer_service.return_value.update_customer_number.assert_not_called()

    @patch("customer.services.customer_merge.Address")
    @patch("shopware.services.CustomerService")
    def test_address_mapping_requires_an_address_of_the_linked_shopware_customer(
        self, customer_service, address_model
    ):
        address = MagicMock(pk=81, api_id="", customer=MagicMock(api_id="b" * 32))
        selected = MagicMock()
        selected.filter.return_value.first.return_value = address
        address_model.objects.select_related.return_value = selected
        duplicates = MagicMock()
        duplicates.exclude.return_value.first.return_value = None
        address_model.objects.filter.return_value = duplicates
        customer_service.return_value.get_by_id.return_value = {
            "data": [{"attributes": {"addresses": [{"id": "c" * 32}]}}]
        }

        result = CustomerIdUpdateService().update_shopware_address_id(81, "c" * 32)

        self.assertEqual(result["new_api_id"], "c" * 32)
        self.assertEqual(address.api_id, "c" * 32)
        address.save.assert_called_once_with(update_fields=["api_id", "updated_at"])

    @patch("customer.services.customer_merge.Address")
    def test_microtech_mapping_uses_business_numbers_and_clears_opaque_ids(self, address_model):
        address = MagicMock(
            pk=81,
            erp_ans_nr=1,
            erp_asp_nr=2,
            erp_ans_id=75,
            erp_asp_id=88,
            erp_combined_id="10001-75-88",
            customer=MagicMock(),
        )
        selected = MagicMock()
        selected.filter.return_value.first.return_value = address
        address_model.objects.select_related.return_value = selected
        candidates = MagicMock()
        candidates.filter.return_value.first.return_value = None
        address_model.objects.filter.return_value.exclude.return_value = candidates

        result = CustomerIdUpdateService().update_microtech_address_mapping(81, 7, 3)

        self.assertEqual(result["old_mapping"], {"ans_nr": 1, "asp_nr": 2})
        self.assertEqual(address.erp_ans_nr, 7)
        self.assertEqual(address.erp_asp_nr, 3)
        self.assertIsNone(address.erp_ans_id)
        self.assertIsNone(address.erp_asp_id)
        self.assertIsNone(address.erp_combined_id)
        address.save.assert_called_once_with(
            update_fields=[
                "erp_ans_nr",
                "erp_asp_nr",
                "erp_ans_id",
                "erp_asp_id",
                "erp_combined_id",
                "updated_at",
            ]
        )


class CustomerDeleteServiceTest(SimpleTestCase):
    @patch("microtech.services.microtech_connection")
    def test_microtech_customer_delete_requires_confirmed_wrapper_result(self, connection):
        client = MagicMock()
        client.delete_customer.return_value = {"status": "DONE", "deleted": True}
        connection.return_value.__enter__.return_value = client

        result = CustomerDeleteService().delete_microtech("10001")

        self.assertEqual(result, {"deleted_erp_nr": "10001"})
        client.delete_customer.assert_called_once_with("10001")


class CustomerIdUpdateViewTest(SimpleTestCase):
    @patch("customer.views.CustomerIdUpdateService")
    def test_microtech_address_mapping_is_dispatched(self, service_class):
        from customer.views import customer_update_ids_api

        service_class.return_value.update_microtech_address_mapping.return_value = {
            "ans_nr": 7,
            "asp_nr": 3,
        }
        request = RequestFactory().post(
            "/admin/customer-merge/api/update-ids/",
            data=json.dumps(
                {
                    "action": "update_microtech_address_mapping",
                    "address_id": 81,
                    "ans_nr": 7,
                    "asp_nr": 3,
                }
            ),
            content_type="application/json",
        )

        response = customer_update_ids_api(request)

        self.assertEqual(response.status_code, 200)
        service_class.return_value.update_microtech_address_mapping.assert_called_once_with(81, 7, 3)


class CustomerMergeMicrotechSearchTest(SimpleTestCase):
    @patch.object(CustomerMergeSearchService, "start_microtech_customer_search")
    def test_customer_number_search_uses_exact_microtech_lookup(self, mock_search):
        mock_search.return_value = {"job_id": 123}

        jobs = CustomerMergeSearchService().start_microtech_resolution_search(
            customer_number="10001",
        )

        mock_search.assert_called_once_with("10001", purpose="resolve")
        self.assertEqual(jobs, [{"job_id": 123, "search_kind": "customer"}])

    def test_name_search_uses_microtech_customer_and_contact_indexes(self):
        requests = dict(CustomerMergeSearchService._microtech_resolution_requests("Müller"))

        self.assertEqual(requests["suchbegriff"]["dataset"], "Adressen")
        self.assertEqual(requests["suchbegriff"]["indexField"], "SuchBeg")
        self.assertEqual(requests["suchbegriff"]["range"]["fromValues"], ["Müller", ""])

        self.assertEqual(requests["nachname"]["dataset"], "Ansprechpartner")
        self.assertEqual(requests["nachname"]["indexField"], "NNa")
        self.assertEqual(requests["nachname"]["range"]["fromValues"], ["Müller", ""])

        self.assertEqual(requests["vorname"]["filter"], "VNa = 'Müller'")
        self.assertIn("AdrNr", requests["vorname"]["fields"])

    def test_first_name_filter_escapes_microtech_filter_quotes(self):
        requests = dict(CustomerMergeSearchService._microtech_resolution_requests("O'Brien"))

        self.assertEqual(requests["vorname"]["filter"], "VNa = 'O''Brien'")

    def test_customer_search_result_unwraps_and_deduplicates_full_customers(self):
        customers = CustomerMergeSearchService._microtech_customers_from_search_result(
            {
                "data": {
                    "customerSearchJob": {
                        "customers": [
                            {"customerNumber": "10001", "name1": "Muster GmbH"},
                            {"customerNumber": "10001", "name1": "Doppelter Treffer"},
                            {"customerNumber": "10002", "firstName": "Mia", "lastName": "Muster"},
                        ]
                    }
                }
            }
        )

        self.assertEqual([customer["erp_nr"] for customer in customers], ["10001", "10002"])
        self.assertEqual(customers[0]["name"], "Muster GmbH")
        self.assertEqual(customers[1]["name"], "Mia Muster")

    def test_running_microtech_search_has_a_non_technical_wait_message(self):
        message = CustomerMergeSearchService._microtech_wait_message(
            "waiting_webhook", "searchCustomers"
        )

        self.assertIn("Microtech durchsucht", message)
        self.assertIn("automatisch ergänzt", message)

    def test_dataset_result_returns_unique_erp_numbers(self):
        result = {
            "records": [
                {"AdrNr": "10001"},
                {"AdrNr": "10001"},
                {"AdrNr": 10002},
                {"NNa": "ohne Nummer"},
            ]
        }

        self.assertEqual(
            CustomerMergeSearchService._erp_numbers_from_dataset_result(result),
            ["10001", "10002"],
        )

    def test_missing_customer_in_successful_job_is_not_a_match(self):
        self.assertIsNone(CustomerMergeSearchService._microtech_customer_from_result({"customer": None}))

    def test_customer_job_result_is_unwrapped_from_graphql_webhook_payload(self):
        customer = CustomerMergeSearchService._microtech_customer_from_result(
            {
                "data": {
                    "customerJob": {
                        "status": "DONE",
                        "customer": {
                            "customerNumber": "10001",
                            "name1": "Muster GmbH",
                        },
                    }
                }
            }
        )

        self.assertEqual(customer["erp_nr"], "10001")
        self.assertEqual(customer["name"], "Muster GmbH")

    def test_customer_job_result_is_normalized_for_merge_column(self):
        result = {
            "customer": {
                "customerNumber": "10001",
                "erpAddressNumber": 42,
                "name1": "Muster GmbH",
                "email": "info@example.com",
                "source": "microtech-com",
                "addresses": [
                    {
                        "addressNumber": 42,
                        "addressSubNumber": 1,
                        "name1": "Muster GmbH",
                        "street": "Musterstraße 1",
                        "zipCode": "12345",
                        "city": "Musterstadt",
                        "country": "DE",
                        "isDefaultShipping": True,
                        "isDefaultBilling": True,
                        "contacts": [
                            {
                                "isDefault": True,
                                "contactNumber": 3,
                                "firstName": "Max",
                                "lastName": "Muster",
                                "email": "max@example.com",
                            }
                        ],
                    }
                ],
            }
        }

        customer = CustomerMergeSearchService._microtech_customer_from_result(result)

        self.assertEqual(customer["erp_nr"], "10001")
        self.assertEqual(customer["erp_id"], 42)
        self.assertEqual(customer["addresses"][0]["firstName"], "Max")
        self.assertEqual(customer["addresses"][0]["email"], "max@example.com")
        self.assertEqual(customer["addresses"][0]["contact_numbers"], [3])
        self.assertEqual(customer["addresses"][0]["contacts"][0]["asp_nr"], 3)
        self.assertEqual(customer["addresses"][0]["contacts"][0]["first_name"], "Max")
        self.assertTrue(customer["addresses"][0]["is_shipping"])
        self.assertTrue(customer["addresses"][0]["is_invoice"])

    @patch("shopware.services.CustomerService")
    def test_shopware_search_marks_default_addresses(self, customer_service_class):
        service = customer_service_class.return_value
        service.get_by_customer_number.return_value = {
            "data": [{
                "id": "customer-id",
                "attributes": {
                    "customerNumber": "10001",
                    "defaultShippingAddressId": "shipping-id",
                    "defaultBillingAddressId": "billing-id",
                    "addresses": [{"id": "shipping-id"}, {"id": "billing-id"}],
                },
            }]
        }

        customer = CustomerMergeSearchService().search_shopware("10001")

        self.assertTrue(customer["addresses"][0]["is_shipping"])
        self.assertFalse(customer["addresses"][0]["is_invoice"])
        self.assertTrue(customer["addresses"][1]["is_invoice"])


class SearchTermParsingTest(SimpleTestCase):
    def test_split_terms_handles_comma_separated_numbers(self):
        self.assertEqual(_split_terms(" 10001 , 10002 ,, 10003 "), ["10001", "10002", "10003"])
        self.assertEqual(_split_terms(""), [])

    def test_has_wildcard_detects_question_mark(self):
        self.assertTrue(_has_wildcard("?@x.de"))
        self.assertFalse(_has_wildcard("plain"))

    def test_wildcard_segments_extract_literal_parts(self):
        self.assertEqual(_wildcard_segments("? Insulation ?"), ["Insulation"])
        self.assertEqual(_wildcard_segments("JACKSON ?"), ["JACKSON"])
        self.assertEqual(_wildcard_segments("?@jackodur.com"), ["@jackodur.com"])
        # A plain term without "?" yields itself.
        self.assertEqual(_wildcard_segments("Müller"), ["Müller"])
        self.assertEqual(_wildcard_segments(""), [])


class AddressSearchResultParsingTest(SimpleTestCase):
    def test_erp_numbers_are_collected_across_datasets_uniquely(self):
        result = {
            "datasets": [
                {"dataset": "Adressen", "records": [{"adrNr": "10001"}, {"adrNr": "10002"}]},
                {"dataset": "Ansprechpartner", "records": [{"adrNr": "10001"}, {"adrNr": "10003"}]},
            ]
        }
        self.assertEqual(
            CustomerMergeSearchService._erp_numbers_from_address_search_result(result),
            ["10001", "10002", "10003"],
        )


class MicrotechResolutionRoutingTest(SimpleTestCase):
    @patch.object(CustomerMergeSearchService, "start_microtech_customer_search")
    def test_multiple_numbers_start_one_customer_search_each(self, mock_search):
        mock_search.side_effect = [{"job_id": 1}, {"job_id": 2}]

        jobs = CustomerMergeSearchService().start_microtech_resolution_search(
            customer_number="10001, 10002",
        )

        self.assertEqual(mock_search.call_count, 2)
        self.assertEqual(jobs, [
            {"job_id": 1, "search_kind": "customer"},
            {"job_id": 2, "search_kind": "customer"},
        ])

    @patch.object(CustomerMergeSearchService, "_submit_address_records_search")
    def test_company_uses_address_records_contains_search(self, mock_addr):
        mock_addr.return_value = [{"job_id": 7, "search_kind": "address_records"}]

        jobs = CustomerMergeSearchService().start_microtech_resolution_search(
            company="? Insulation ?",
        )

        mock_addr.assert_called_once_with("Insulation")
        self.assertEqual(jobs, [{"job_id": 7, "search_kind": "address_records"}])

    @patch.object(CustomerMergeSearchService, "_submit_address_records_search")
    def test_wildcard_last_name_uses_address_records(self, mock_addr):
        mock_addr.return_value = [{"job_id": 8, "search_kind": "address_records"}]

        jobs = CustomerMergeSearchService().start_microtech_resolution_search(
            last_name="JACKSON ?",
        )

        mock_addr.assert_called_once_with("JACKSON")
        self.assertEqual(jobs, [{"job_id": 8, "search_kind": "address_records"}])


class ShopwareCustomerMergeTest(SimpleTestCase):
    source = "a" * 32
    target = "b" * 32
    operation = "c" * 32
    billing = "d" * 32
    shipping = "e" * 32

    def setUp(self):
        self.client_patch = patch("shopware.services.CustomerService")
        self.client = self.client_patch.start().return_value
        self.addCleanup(self.client_patch.stop)
        self.service = ShopwareCustomerMergeService()

    def response(self, *, preview=False, copied=True):
        data = {
            "sourceId": self.source, "targetId": self.target,
            "credentialSourceId": self.source if copied else self.target,
            "credentialsCopied": copied, "addressesMoved": 5, "ordersMoved": 501,
            "defaultBillingAddressId": self.billing, "defaultShippingAddressId": self.shipping,
        }
        if preview:
            data.update({
                "previewToken": "snapshot-token",
                "defaultBillingAddressId": self.billing, "defaultShippingAddressId": self.shipping,
            })
        else:
            data.update({
                "operationId": self.operation, "status": "merged", "sourceDeleted": True,
                "lastLogin": "2026-09-14T10:00:00+00:00",
                "verified": {field: True for field in self.service.VERIFIED_FIELDS},
            })
        return data

    def merge(self, **overrides):
        kwargs = {
            "keep_sw_id": self.target, "delete_sw_id": self.source,
            "operation_id": self.operation, "preview_token": "snapshot-token",
        }
        return self.service.merge(**{**kwargs, **overrides})

    def upstream_error(self, status, code=None, detail="Ein sicherer Plugin-Fehlertext."):
        response = MagicMock()
        response.status_code = status
        response.json.return_value = {"errors": [{"code": code, "detail": detail}]} if code else {}
        cause = RuntimeError("raw upstream error must never be exposed")
        cause.response = response
        wrapper = RuntimeError("wrapper includes sensitive response")
        wrapper.__cause__ = cause
        return wrapper

    def test_preview_uses_only_plugin_and_authoritative_credential_source(self):
        self.client._request_with_retry.return_value = self.response(preview=True)
        result = self.service.preview(keep_sw_id=self.target, delete_sw_id=self.source)
        self.assertEqual(result["credentialSourceId"], self.source)
        self.client._request_with_retry.assert_called_once_with(
            "request_post", "/_action/gc-customer-merge/preview",
            payload={"targetId": self.target, "sourceId": self.source},
        )
        self.client.get_by_id.assert_not_called()

    def test_newer_source_credentials_keep_selected_target(self):
        self.client._request_with_retry.return_value = self.response()
        result = self.merge()
        self.assertEqual(result["targetId"], self.target)
        self.assertEqual(result["credentialSourceId"], self.source)
        self.assertTrue(result["credentialsCopied"])
        self.assertEqual(result["addressesMoved"], 5)
        self.assertEqual(result["ordersMoved"], 501)
        self.client._request_with_retry.assert_called_once_with(
            "request_post", "/_action/gc-customer-merge/execute",
            payload={
                "sourceId": self.source, "targetId": self.target,
                "previewToken": "snapshot-token", "operationId": self.operation,
            },
        )
        self.client.request_patch.assert_not_called()
        self.client.request_delete.assert_not_called()
        self.client.update_customer.assert_not_called()

    def test_target_credentials_can_be_retained(self):
        self.client._request_with_retry.return_value = self.response(copied=False)
        self.assertFalse(self.merge()["credentialsCopied"])

    def test_never_logged_in_target_retains_credentials_and_null_timestamp(self):
        response = self.response(copied=False)
        response["lastLogin"] = None
        self.client._request_with_retry.return_value = response
        for result in (self.merge(), self.service.status(operation_id=self.operation)):
            self.assertEqual(result["targetId"], self.target)
            self.assertEqual(result["credentialSourceId"], self.target)
            self.assertFalse(result["credentialsCopied"])
            self.assertIsNone(result["lastLogin"])

    def test_no_password_fields_leave_adapter(self):
        response = self.response()
        response.update({"password": "hidden", "legacyPassword": "hidden", "hash": "hidden", "email": "hidden"})
        response["verified"]["password"] = "hidden"
        self.client._request_with_retry.return_value = response
        result = self.merge()
        self.assertNotIn("hidden", json.dumps(result))
        self.assertEqual(set(result["verified"]), set(self.service.VERIFIED_FIELDS))

    def test_defaults_are_sent_only_if_selected(self):
        self.client._request_with_retry.return_value = self.response(preview=True)
        self.service.preview(
            keep_sw_id=self.target, delete_sw_id=self.source,
            default_billing_address_id=self.billing, default_shipping_address_id="",
        )
        payload = self.client._request_with_retry.call_args.kwargs["payload"]
        self.assertEqual(payload["defaultBillingAddressId"], self.billing)
        self.assertNotIn("defaultShippingAddressId", payload)

    def test_preview_and_execute_keep_identical_default_selection(self):
        for selected in ("", self.billing):
            with self.subTest(selected=selected):
                self.client._request_with_retry.return_value = self.response(preview=True)
                self.service.preview(
                    keep_sw_id=self.target, delete_sw_id=self.source,
                    default_billing_address_id=selected,
                )
                preview_payload = self.client._request_with_retry.call_args.kwargs["payload"].copy()
                self.client._request_with_retry.return_value = self.response()
                self.merge(default_billing_address_id=selected)
                execute_payload = self.client._request_with_retry.call_args.kwargs["payload"].copy()
                execute_payload.pop("operationId")
                execute_payload.pop("previewToken")
                self.assertEqual(execute_payload, preview_payload)
                self.assertNotIn("defaultShippingAddressId", execute_payload)

    def test_final_result_must_match_explicitly_selected_defaults(self):
        self.client._request_with_retry.return_value = self.response()
        result = self.merge(default_billing_address_id=self.billing, default_shipping_address_id=self.shipping)
        self.assertEqual(result["defaultBillingAddressId"], self.billing)
        for key in ("default_billing_address_id", "default_shipping_address_id"):
            with self.subTest(key=key), self.assertRaises(ShopwareMergeError) as raised:
                self.merge(**{key: "f" * 32})
            self.assertTrue(raised.exception.uncertain)

    def test_ids_are_validated_before_api_calls(self):
        for value in ("", "abc", "../customer", None, "f" * 33):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.merge(keep_sw_id=value)
        self.client._request_with_retry.assert_not_called()

    def test_identical_ids_are_rejected(self):
        with self.assertRaisesMessage(ValueError, "unterschiedlich"):
            self.merge(keep_sw_id=self.source)
        self.client._request_with_retry.assert_not_called()

    def test_execute_requires_preview_and_operation(self):
        for overrides in ({"preview_token": ""}, {"preview_token": {}}, {"operation_id": ""}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.merge(**overrides)
        self.client._request_with_retry.assert_not_called()

    def test_repeated_execute_keeps_same_operation_and_preview(self):
        self.client._request_with_retry.return_value = self.response()
        self.merge()
        first = self.client._request_with_retry.call_args
        self.merge()
        self.assertEqual(first, self.client._request_with_retry.call_args)

    def test_swapped_target_or_incomplete_verification_is_not_success(self):
        bad_results = []
        data = self.response()
        data["targetId"], data["sourceId"] = self.source, self.target
        bad_results.append(data)
        for field in self.service.VERIFIED_FIELDS:
            data = self.response()
            data["verified"][field] = False
            bad_results.append(data)
        for field, value in (
            ("sourceDeleted", False), ("operationId", "f" * 32),
            ("addressesMoved", True), ("ordersMoved", -1),
            ("credentialsCopied", False), ("credentialSourceId", "f" * 32),
            ("defaultBillingAddressId", None), ("defaultShippingAddressId", ""),
        ):
            data = self.response()
            data[field] = value
            bad_results.append(data)
        for data in bad_results:
            with self.subTest(data=data):
                self.client._request_with_retry.return_value = data
                with self.assertRaises(ShopwareMergeError) as raised:
                    self.merge()
                self.assertTrue(raised.exception.uncertain)

    def test_malformed_preview_or_changed_defaults_prevents_execution(self):
        for field, value in (("previewToken", ""), ("defaultBillingAddressId", "f" * 32)):
            with self.subTest(field=field):
                data = self.response(preview=True)
                data[field] = value
                self.client._request_with_retry.return_value = data
                with self.assertRaises(ShopwareMergeError) as raised:
                    self.service.preview(
                        keep_sw_id=self.target, delete_sw_id=self.source,
                        default_billing_address_id=self.billing,
                    )
                self.assertFalse(raised.exception.uncertain)

    def test_status_returns_confirmed_operation(self):
        self.client._request_with_retry.return_value = self.response()
        result = self.service.status(operation_id=self.operation)
        self.assertEqual(result["operationId"], self.operation)
        self.client._request_with_retry.assert_called_once_with(
            "request_get", f"/_action/gc-customer-merge/status/{self.operation}"
        )

    def test_status_not_found_is_not_a_successful_merge(self):
        self.client._request_with_retry.return_value = {"status": "not_found", "operationId": self.operation}
        self.assertEqual(self.service.status(operation_id=self.operation)["status"], "not_found")

    def test_status_rejects_wrong_operation(self):
        self.client._request_with_retry.return_value = {"status": "not_found", "operationId": "f" * 32}
        with self.assertRaises(ShopwareMergeError):
            self.service.status(operation_id=self.operation)

    def test_stale_preview_returns_safe_code_and_message(self):
        self.client._request_with_retry.side_effect = self.upstream_error(
            409, "GC_MERGE_PREVIEW_STALE", "Die Kundendaten wurden seit der Vorschau geändert."
        )
        with self.assertRaises(ShopwareMergeError) as raised:
            self.merge()
        self.assertEqual(raised.exception.code, "GC_MERGE_PREVIEW_STALE")
        self.assertEqual(raised.exception.status, 409)
        self.assertFalse(raised.exception.uncertain)
        self.assertIn("seit der Vorschau", str(raised.exception))

    def test_operation_conflict_and_server_errors_require_status_check(self):
        for status, code in ((409, "GC_MERGE_OPERATION_CONFLICT"), (500, "GC_MERGE_FAILED")):
            with self.subTest(code=code):
                self.client._request_with_retry.side_effect = self.upstream_error(status, code)
                with self.assertRaises(ShopwareMergeError) as raised:
                    self.merge()
                self.assertTrue(raised.exception.uncertain)

    def test_connection_failure_does_not_log_or_expose_raw_exception(self):
        self.client._request_with_retry.side_effect = RuntimeError("password=super-secret")
        with self.assertRaises(ShopwareMergeError) as raised:
            self.merge()
        self.assertNotIn("super-secret", str(raised.exception))
        self.assertTrue(raised.exception.uncertain)
        self.assertIn("Vorgangsstatus", str(raised.exception))

    def test_missing_plugin_never_falls_back_to_entity_mutations(self):
        self.client._request_with_retry.side_effect = self.upstream_error(404)
        with self.assertRaisesMessage(ShopwareMergeError, "GecoCustomerMerge"):
            self.merge()
        self.client.request_patch.assert_not_called()
        self.client.request_delete.assert_not_called()
        self.client.get_by_id.assert_not_called()

    def test_permission_error_is_actionable(self):
        self.client._request_with_retry.side_effect = self.upstream_error(403)
        with self.assertRaisesMessage(ShopwareMergeError, "Merge-ACL") as raised:
            self.merge()
        # Permission may have changed after an earlier timed-out execution.
        # Losing the operation ID would lose the only safe way to recover it.
        self.assertTrue(raised.exception.uncertain)


class ShopwareCustomerMergeViewTest(SimpleTestCase):
    def request(self, body=None, *, query="", method="post", permitted=True):
        factory = RequestFactory()
        if method == "post":
            request = factory.post("/", data=json.dumps(body), content_type="application/json")
        else:
            request = factory.get("/" + query)
        request.user = MagicMock()
        request.user.has_perms.return_value = permitted
        request.user.has_perm.return_value = permitted
        return request

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_preview_is_separate_from_execution(self, service_class):
        from customer.views import customer_merge_shopware_api
        service_class.return_value.preview.return_value = {"previewToken": "token"}
        result = customer_merge_shopware_api(self.request({
            "action": "preview", "keep_sw_id": "b" * 32, "delete_sw_id": "a" * 32,
        }))
        self.assertEqual(result.status_code, 200)
        service_class.return_value.preview.assert_called_once()
        self.assertTrue(service_class.return_value.preview.call_args.kwargs["include_comparison"])
        service_class.return_value.merge.assert_not_called()

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_old_unguarded_execute_contract_is_rejected(self, service_class):
        from customer.views import customer_merge_shopware_api
        result = customer_merge_shopware_api(self.request({"keep_sw_id": "b" * 32, "delete_sw_id": "a" * 32}))
        self.assertEqual(result.status_code, 400)
        service_class.return_value.merge.assert_not_called()

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_execute_passes_stable_operation_and_token(self, service_class):
        from customer.views import customer_merge_shopware_api
        service_class.return_value.merge.return_value = {
            "status": "merged", "sourceId": "a" * 32, "targetId": "b" * 32,
        }
        service_class.return_value.cleanup_django_source_after_merge.return_value = {
            "status": "deleted", "orders_moved": 2, "addresses_moved": 1,
        }
        result = customer_merge_shopware_api(self.request({
            "action": "execute", "keep_sw_id": "b" * 32, "delete_sw_id": "a" * 32,
            "operation_id": "c" * 32, "preview_token": "snapshot",
        }))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(service_class.return_value.merge.call_args.kwargs["operation_id"], "c" * 32)
        self.assertEqual(service_class.return_value.merge.call_args.kwargs["preview_token"], "snapshot")
        service_class.return_value.cleanup_django_source_after_merge.assert_called_once_with(
            source_sw_id="a" * 32, target_sw_id="b" * 32,
        )
        self.assertEqual(json.loads(result.content)["djangoCleanup"]["status"], "deleted")

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_status_uses_get_without_starting_an_operation(self, service_class):
        from customer.views import customer_merge_shopware_api
        service_class.return_value.status.return_value = {"status": "not_found"}
        result = customer_merge_shopware_api(self.request(method="get", query="?action=status&operation_id=" + "c" * 32))
        self.assertEqual(result.status_code, 200)
        service_class.return_value.status.assert_called_once_with(operation_id="c" * 32)
        service_class.return_value.merge.assert_not_called()

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_confirmed_status_retries_local_source_cleanup(self, service_class):
        from customer.views import customer_merge_shopware_api
        service_class.return_value.status.return_value = {
            "status": "merged", "sourceId": "a" * 32, "targetId": "b" * 32,
        }
        service_class.return_value.cleanup_django_source_after_merge.return_value = {
            "status": "already_removed", "orders_moved": 0, "addresses_moved": 0,
        }
        result = customer_merge_shopware_api(self.request(
            method="get", query="?action=status&operation_id=" + "c" * 32,
        ))
        self.assertEqual(result.status_code, 200)
        service_class.return_value.cleanup_django_source_after_merge.assert_called_once_with(
            source_sw_id="a" * 32, target_sw_id="b" * 32,
        )

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_permission_denied_before_any_plugin_call(self, service_class):
        from customer.views import customer_merge_shopware_api
        result = customer_merge_shopware_api(self.request({"action": "execute"}, permitted=False))
        self.assertEqual(result.status_code, 403)
        service_class.assert_not_called()

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_stale_preview_is_exposed_with_structured_error(self, service_class):
        from customer.views import customer_merge_shopware_api
        service_class.return_value.merge.side_effect = ShopwareMergeError(
            "Neue Vorschau erforderlich.", code="GC_MERGE_PREVIEW_STALE", status=409,
        )
        result = customer_merge_shopware_api(self.request({"action": "execute"}))
        self.assertEqual(result.status_code, 409)
        self.assertEqual(json.loads(result.content)["code"], "GC_MERGE_PREVIEW_STALE")

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_non_object_json_is_rejected(self, service_class):
        from customer.views import customer_merge_shopware_api
        result = customer_merge_shopware_api(self.request([]))
        self.assertEqual(result.status_code, 400)
        service_class.return_value.merge.assert_not_called()

    @patch("customer.views.ShopwareCustomerMergeService")
    def test_unexpected_errors_are_not_leaked(self, service_class):
        from customer.views import customer_merge_shopware_api
        service_class.return_value.merge.side_effect = RuntimeError("password=secret")
        result = customer_merge_shopware_api(self.request({"action": "execute"}))
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("secret", result.content.decode())


class CustomerMergeDjangoMutationViewTest(SimpleTestCase):
    def request(self, body, *, permitted=True):
        request = RequestFactory().post("/", data=json.dumps(body), content_type="application/json")
        request.user = MagicMock()
        request.user.has_perm.return_value = permitted
        return request

    @patch("customer.views.CustomerSyncDirectionService")
    def test_adopt_shopware_address_calls_single_address_import(self, service_class):
        from customer.views import customer_adopt_shopware_address_api
        service_class.return_value.import_shopware_address.return_value = {"address_id": 42}
        result = customer_adopt_shopware_address_api(self.request({
            "erp_nr": "10001", "shopware_address_id": "a" * 32,
        }))
        self.assertEqual(result.status_code, 200)
        service_class.return_value.import_shopware_address.assert_called_once_with(
            erp_nr="10001", shopware_address_id="a" * 32,
        )

    @patch("customer.views.CustomerDeleteService")
    def test_delete_django_customer_uses_local_delete_service(self, service_class):
        from customer.views import customer_delete_django_api
        service_class.return_value.delete_django.return_value = {"deleted": "10001 (Test)"}
        result = customer_delete_django_api(self.request({"erp_nr": "10001"}))
        self.assertEqual(result.status_code, 200)
        service_class.return_value.delete_django.assert_called_once_with("10001")


class ShopwareMergeComparisonTest(SimpleTestCase):
    def setUp(self):
        self.client_patch = patch("shopware.services.CustomerService")
        self.client = self.client_patch.start().return_value
        self.addCleanup(self.client_patch.stop)
        self.service = ShopwareCustomerMergeService()
        self.source, self.target = "a" * 32, "b" * 32
        self.customers = [
            {"id": self.source, "customerNumber": "10001", "email": "source@example.invalid", "password": "NEVER-FORWARD"},
            {"id": self.target, "customerNumber": "10002", "email": "target@example.invalid"},
        ]
        self.addresses = [
            {"id": f"{index + 1:032x}", "customerId": self.source, "additionalAddressLine2": "Hinterhaus", "hash": "NEVER-FORWARD"}
            for index in range(105)
        ] + [{"id": "d" * 32, "customerId": self.target}]
        self.plan = {
            "sourceId": self.source, "targetId": self.target, "credentialSourceId": self.source,
            "credentialsCopied": True, "addressesMoved": 105, "ordersMoved": 501,
            "previewToken": "signed-plan", "defaultBillingAddressId": "d" * 32,
            "defaultShippingAddressId": "d" * 32,
        }
        self.client._request_with_retry.side_effect = self.api_response

    def api_response(self, method, path, *, payload):
        self.assertEqual(method, "request_post")
        if path == "/search/customer":
            return {"data": self.customers}
        if path == "/search/customer-address":
            start = (payload["page"] - 1) * payload["limit"]
            return {"data": self.addresses[start:start + payload["limit"]], "total": len(self.addresses)}
        self.assertEqual(path, "/_action/gc-customer-merge/preview")
        return self.plan

    def preview(self):
        return self.service.preview(include_comparison=True, keep_sw_id=self.target, delete_sw_id=self.source)

    def test_fresh_comparison_includes_every_address_and_no_hashes(self):
        result = self.preview()
        self.assertEqual(len(result["comparison"]["source"]["addresses"]), 105)
        self.assertEqual(len(result["comparison"]["target"]["addresses"]), 1)
        self.assertEqual(result["comparison"]["source"]["addresses"][-1]["additionalAddressLine2"], "Hinterhaus")
        self.assertNotIn("NEVER-FORWARD", json.dumps(result))
        calls = self.client._request_with_retry.call_args_list
        self.assertEqual([call.args[1] for call in calls], [
            "/search/customer", "/search/customer-address", "/search/customer-address",
            "/_action/gc-customer-merge/preview",
            "/search/customer", "/search/customer-address", "/search/customer-address",
        ])
        requested_fields = json.dumps([call.kwargs["payload"].get("includes") for call in calls])
        for field in ('"password"', '"legacyPassword"', '"hash"', '"customFields"'):
            self.assertNotIn(field, requested_fields)
        self.client.request_patch.assert_not_called()
        self.client.request_delete.assert_not_called()

    def test_changing_customer_during_preview_is_rejected(self):
        def response(method, path, *, payload):
            if path == "/_action/gc-customer-merge/preview":
                self.customers[0]["email"] = "changed@example.invalid"
            return self.api_response(method, path, payload=payload)
        self.client._request_with_retry.side_effect = response
        with self.assertRaises(ShopwareMergeError) as raised:
            self.preview()
        self.assertEqual(raised.exception.code, "GC_MERGE_PREVIEW_STALE")
        self.assertFalse(raised.exception.uncertain)

    def test_plugin_count_mismatch_rejects_incomplete_address_preview(self):
        self.plan["addressesMoved"] = 106
        with self.assertRaises(ShopwareMergeError) as raised:
            self.preview()
        self.assertEqual(raised.exception.code, "GC_MERGE_PREVIEW_STALE")

    def test_missing_customer_never_falls_back_to_search_cache(self):
        self.customers.pop()
        with self.assertRaises(ShopwareMergeError) as raised:
            self.preview()
        self.assertEqual(raised.exception.code, "GC_MERGE_COMPARISON_UNAVAILABLE")
        self.assertEqual(self.client._request_with_retry.call_count, 1)

    def test_repeating_address_page_is_rejected(self):
        self.addresses[100] = self.addresses[0]
        with self.assertRaises(ShopwareMergeError):
            self.preview()

    def test_upstream_errors_cannot_leak_secrets(self):
        self.client._request_with_retry.side_effect = RuntimeError("NEVER-FORWARD")
        with self.assertRaises(ShopwareMergeError) as raised:
            self.preview()
        self.assertNotIn("NEVER-FORWARD", str(raised.exception))


@skipUnless(shutil.which("node"), "Node is needed for the isolated browser-state checks")
class ShopwareMergeBrowserStateTest(SimpleTestCase):
    """Exercise the actual template JS with fake DOM/network and no database."""

    def test_template_has_one_confirmation_button_inside_native_dialog(self):
        from django.template.loader import get_template

        get_template("admin/customer_merge.html")  # Compile with Django, without rendering or DB access.
        template = (Path(__file__).resolve().parents[1] / "templates/admin/customer_merge.html").read_text()
        markup = template.split("<script>", 1)[0]
        modal = markup.split('<dialog id="sw-merge-modal"', 1)[1].split("</dialog>", 1)[0]
        self.assertEqual(markup.count('id="sw-merge-btn"'), 1)
        self.assertIn('id="sw-merge-btn"', modal)
        self.assertIn('aria-labelledby="sw-merge-modal-title"', modal)
        self.assertIn('id="sw-merge-preview"', modal)
        self.assertIn('id="sw-merge-result"', modal)

    def test_customer_merge_does_not_offer_microtech_customer_deletion(self):
        template = (Path(__file__).resolve().parents[1] / "templates/admin/customer_merge.html").read_text()
        self.assertNotIn("microtech-Kunde markieren", template)
        self.assertNotIn("deleteMicrotechCustomer", template)
        self.assertNotIn("delete-microtech-customer", template)

    def run_js(self, assertions, *, saved=None):
        template = (Path(__file__).resolve().parents[1] / "templates/admin/customer_merge.html").read_text()
        badges = "function standardAddressBadges(" + template.split("function standardAddressBadges(", 1)[1].split("/* ── search", 1)[0]
        identifiers = "function editableCustomerNumberField(" + template.split("function editableCustomerNumberField(", 1)[1].split("function toggleSection(", 1)[0]
        normalize = "function normalize(" + template.split("function normalize(", 1)[1].split("function standardAddressBadges(", 1)[0]
        renderer = "function renderRows(" + template.split("function renderRows(", 1)[1].split("function renderToggle(", 1)[0]
        script = identifiers + normalize + badges + renderer + "const swMergeStorageKey =" + template.split("const swMergeStorageKey =", 1)[1].split("</script>", 1)[0]
        harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const elements = new Map();
const stored = new Map();
const savedOperation = SAVED_OPERATION;
if (savedOperation) stored.set('gc-sw6-merge-operation-v1', JSON.stringify(savedOperation));
let networkCalls = [];
let confirmCount = 0;
let refreshCount = 0;
const SYSTEMS = [
  {key: 'shopware', label: 'SW6', icon: 'shopping_bag'},
  {key: 'django', label: 'GC-Bridge', icon: 'database'},
  {key: 'microtech', label: 'Microtech', icon: 'precision_manufacturing'},
];
let searchData = {};
const element = id => {
  if (!elements.has(id)) elements.set(id, {
    value: '', innerHTML: '', disabled: false, open: false, hidden: false, listeners: {},
    addEventListener(name, handler) { this.listeners[name] = handler; },
    showModal() { this.open = true; },
    close() { this.open = false; this.listeners.close?.(); },
    classList: {removed: [], remove(name) { this.removed.push(name); }, add() {}},
  });
  return elements.get(id);
};
element('sw-merge-keep').value = 'b'.repeat(32);
element('sw-merge-delete').value = 'a'.repeat(32);
const sandbox = {
  assert, console, Uint8Array, AbortController, URLSearchParams,
  crypto: require('node:crypto').webcrypto,
  SYSTEMS, searchData,
  getCellState: () => 'found', isRowLoading: () => false,
  columnStatusLabel: () => 'geladen',
  CSRF: 'test-only',
  sessionStorage: {getItem: key => stored.get(key) || null, setItem: (key, val) => stored.set(key, val), removeItem: key => stored.delete(key)},
  document: {getElementById: element},
  spinner: () => 'loading', esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  comparisonFixture: (source = 'a'.repeat(32), target = 'b'.repeat(32)) => ({
    source: {id: source, customerNumber: '10001', email: 'quelle@example.invalid',
      addresses: Array.from({length: 5}, (_, index) => ({id: String(index + 1).repeat(32), customerId: source, street: 'Quellstraße ' + (index + 1)}))},
    target: {id: target, customerNumber: '10002', email: 'ziel@example.invalid',
      defaultBillingAddressId: 'd'.repeat(32), defaultShippingAddressId: 'd'.repeat(32),
      addresses: [{id: 'd'.repeat(32), customerId: target, street: 'Zielstraße 1'}]},
  }),
  collectShopwareCustomers: () => [], shopwareCustomerById: () => null,
  confirm: () => { confirmCount++; return true; },
  alert: message => { throw new Error(message); },
  setTimeout: () => 1, clearTimeout: () => {},
  doSearch: () => { refreshCount++; },
  fetch: async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : null;
    networkCalls.push({url, body});
    if (body?.action === 'execute') {
      assert.equal(JSON.parse(stored.get('gc-sw6-merge-operation-v1')).operation_id, body.operation_id,
        'Idempotency key must be durable before the first HTTP write');
    }
    return sandbox.nextResponse(url, options);
  },
  nextResponse: async () => { throw new Error('simulated timeout'); },
  networkCalls, stored, elements,
  getConfirmCount: () => confirmCount,
};
const script = SCRIPT;
const assertions = ASSERTIONS;
vm.runInNewContext(script + '\n(async () => {' + assertions + '\n})().catch(error => { console.error(error); process.exitCode = 1; });', {...sandbox, process});
'''.replace("SCRIPT;", json.dumps(script) + ";").replace("ASSERTIONS;", json.dumps(assertions) + ";").replace("SAVED_OPERATION;", json.dumps(saved) + ";")
        result = subprocess.run([shutil.which("node"), "-e", harness], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_timeout_keeps_durable_operation_and_retry_uses_same_id(self):
        self.run_js(r'''
const selection = swMergeSelection();
openShopwareMergeModal();
swMergePreview = {selection, data: {sourceId: selection.delete_sw_id, targetId: selection.keep_sw_id,
  credentialsCopied: true, addressesMoved: 5, ordersMoved: 501, previewToken: 'snapshot'}};
await executeShopwareMerge();
assert.equal(networkCalls.length, 1);
assert.ok(swMergePending);
assert.equal(swMergeRetryAllowed, false);
const original = JSON.stringify(networkCalls[0].body);
const operation = swMergePending.operation_id;
await executeShopwareMerge();
assert.equal(networkCalls.length, 1, 'A pending operation blocks creating a new key');
// Check the API first; only then permit resending the exact original request.
nextResponse = async () => ({ok: true, json: async () => ({status: 'not_found', operationId: operation})});
// The fetch closure uses the outer harness object, so override fetch for this stage.
fetch = async (url, options) => {
  networkCalls.push({url, body: options.body ? JSON.parse(options.body) : null});
  return {ok: true, json: async () => ({status: 'not_found', operationId: operation})};
};
await checkShopwareMergeStatus();
assert.equal(swMergeRetryAllowed, true);
assert.ok(networkCalls[1].url.includes(operation));
fetch = async (url, options) => {
  networkCalls.push({url, body: JSON.parse(options.body)});
  throw new Error('still unavailable');
};
await retryShopwareMerge();
assert.equal(JSON.stringify(networkCalls[2].body), original);
assert.equal(swMergePending.operation_id, operation);
''')

    def test_reload_exposes_recovery_before_any_customer_search(self):
        self.run_js(r'''
assert.equal(swMergePending.operation_id, 'c'.repeat(32));
assert.ok(elements.get('results-area').classList.removed.includes('hidden'));
assert.ok(elements.get('sw-merge-result').innerHTML.includes('wiederhergestellt'));
assert.equal(elements.get('sw-merge-btn').disabled, true);
assert.equal(elements.get('sw-merge-retry-btn').disabled, true);
assert.equal(networkCalls.length, 0, 'Recovery never starts a merge automatically');
''', saved={
            "action": "execute", "keep_sw_id": "b" * 32, "delete_sw_id": "a" * 32,
            "operation_id": "c" * 32, "preview_token": "existing-snapshot",
        })

    def test_ui_does_not_add_resolved_defaults_to_signed_selection(self):
        self.run_js(r'''
const source = 'a'.repeat(32), target = 'b'.repeat(32);
fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  networkCalls.push({url, body});
  if (body.action === 'preview') return {ok: true, json: async () => ({
    sourceId: source, targetId: target, credentialSourceId: source, credentialsCopied: true,
    addressesMoved: 5, ordersMoved: 1, previewToken: 'signed-with-omitted-defaults',
    defaultBillingAddressId: 'd'.repeat(32), defaultShippingAddressId: 'e'.repeat(32),
    comparison: comparisonFixture(source, target),
  })};
  throw new Error('simulated timeout');
};
await loadShopwareMergePreview();
assert.equal(swMergePreview.data.defaultBillingAddressId, 'd'.repeat(32));
await executeShopwareMerge();
assert.equal(networkCalls.length, 2);
const previewBody = networkCalls[0].body, executeBody = networkCalls[1].body;
for (const body of [previewBody, executeBody]) {
  assert.equal(Object.hasOwn(body, 'default_billing_address_id'), false);
  assert.equal(Object.hasOwn(body, 'default_shipping_address_id'), false);
}
assert.equal(executeBody.keep_sw_id, previewBody.keep_sw_id);
assert.equal(executeBody.delete_sw_id, previewBody.delete_sw_id);
assert.equal(executeBody.preview_token, 'signed-with-omitted-defaults');
''')

    def test_merge_section_has_no_default_address_selectors(self):
        self.run_js(r'''
collectShopwareCustomers = () => [
  {id: 'a'.repeat(32), number: 'A', email: 'a@example.invalid'},
  {id: 'b'.repeat(32), number: 'B', email: 'b@example.invalid'},
];
renderShopwareMergeSection();
const html = elements.get('sw-merge-section').innerHTML;
for (const id of ['sw-merge-defaults', 'sw-merge-billing', 'sw-merge-shipping']) {
  assert.equal(html.includes(id), false);
}
assert.ok(html.includes('am Zielkunden eingestellten Standardadressen bleiben erhalten'));
assert.equal(html.includes('id="sw-merge-btn"'), false, 'Merge can only be confirmed inside the modal');
assert.equal(html.includes('id="sw-merge-preview"'), false, 'Preview content belongs to the modal');
assert.ok(html.includes('>Vorschau laden</button>'));
assert.deepEqual(Object.keys(swMergeSelection()).sort(), ['delete_sw_id', 'keep_sw_id']);
''')

    def test_modal_compares_all_addresses_and_keeps_target_profile(self):
        self.run_js(r'''
const comparison = comparisonFixture();
comparison.source.firstName = '<img src=x onerror=alert(1)>';
comparison.target.firstName = 'Ziel-Vorname';
comparison.source.lastLogin = '2026-09-14T10:00:00Z';
comparison.source.addresses[0].additionalAddressLine2 = 'Hinterhaus / 3. Stock';
const html = renderShopwareMergeComparison({comparison, sourceId: comparison.source.id,
  targetId: comparison.target.id, credentialSourceId: comparison.source.id, credentialsCopied: true,
  addressesMoved: 5, ordersMoved: 501, defaultBillingAddressId: 'd'.repeat(32), defaultShippingAddressId: 'd'.repeat(32)});
assert.equal((html.match(/<details open/g) || []).length, 6);
for (const value of ['Quellstraße 5', 'Zielstraße 1', 'Hinterhaus / 3. Stock', 'Ziel-Vorname', 'quelle@example.invalid', 'ziel@example.invalid', 'Geschützt · Konto 10001']) assert.ok(html.includes(value), value);
assert.equal(html.includes('<img'), false);
assert.ok(html.includes('&lt;img'));
assert.ok(html.includes('Lieferadresse'));
assert.ok(html.includes('Rechnungsadresse'));
assert.ok(html.includes('merge-direction'));
assert.ok(html.includes('Ziel vorher: ziel@example.invalid'));
''')

    def test_missing_login_retains_target_pair_in_comparison(self):
        self.run_js(r'''
const comparison = comparisonFixture();
const html = renderShopwareMergeComparison({comparison, sourceId: comparison.source.id,
  targetId: comparison.target.id, credentialsCopied: false, addressesMoved: 5, ordersMoved: 1});
assert.ok(html.includes('Noch nie eingeloggt'));
assert.ok(html.includes('Geschützt · Konto 10002'));
assert.ok(html.includes('Das Login-Paar des Zielkunden bleibt erhalten'));
''')

    def test_identifier_cards_only_show_editable_shopware_mappings(self):
        self.run_js(r'''
const raw = {id: 42, erp_nr: '10001', erp_id: 2345, api_id: 'a'.repeat(32), addresses: [{
  id: 81, api_id: 'c'.repeat(32), erp_nr: 10001, erp_ans_id: 75, erp_ans_nr: 2,
  erp_asp_id: 88, erp_asp_nr: 3, erp_combined_id: '10001-75-88',
}]};
const normalized = normalize(raw, 'django');
const customerHtml = customerIdentifiers('10001', 'django', raw, normalized);
for (const value of ['AdrNr', '10001', 'SW6-ID', raw.api_id, 'update_shopware_id']) assert.ok(customerHtml.includes(value), value);
assert.ok(customerHtml.includes('Django-Kunde löschen'));
assert.ok(customerHtml.includes('deleteDjangoCustomer'));
assert.ok(customerHtml.includes('shopware-id-field'));
assert.ok(customerHtml.includes('<textarea'));
const shopwareHtml = shopwareCustomerMapping('10001', {id: raw.api_id});
assert.ok(shopwareHtml.includes('shopware-id-field'));
assert.ok(shopwareHtml.includes('shopware-id-value'));
assert.ok(shopwareHtml.includes(raw.api_id));
for (const hidden of ['Django-ID', 'ERP-ID', '2345', 'ERP-Kombi-ID', 'AnsId', 'AnsNr', 'AspId', 'AspNr']) assert.equal(customerHtml.includes(hidden), false, hidden);
const addressHtml = editableShopwareMapping('SW6-Adress-ID', normalized.addresses[0].apiId, 'update_shopware_address_id', 'address_id', raw.addresses[0].id, '10001');
assert.ok(addressHtml.includes(raw.addresses[0].api_id));
assert.ok(addressHtml.includes('update_shopware_address_id'));
assert.equal(Object.hasOwn(normalized.addresses[0], 'addressNumber'), false);
assert.equal(identifierRows([['Test', 0]]).includes('<dd>0</dd>'), true);
assert.ok(identifierRows([['Test', '<script>']]).includes('&lt;script&gt;'));
const microtech = normalize({status: 'microtech-com', addresses: [{ans_id: 10001, ans_nr: 2, contact_numbers: [1, 3]}]}, 'microtech');
assert.deepEqual(microtech.extra, []);
assert.equal(Object.hasOwn(microtech.addresses[0], 'identifiers'), false);
assert.equal(microtech.addresses[0].microtechAddressNumber, 2);
assert.deepEqual(microtech.addresses[0].contacts.map(contact => contact.microtechContactNumber), [1, 3]);
''')

    def test_address_comparison_groups_microtech_contacts_with_their_bridge_mapping(self):
        self.run_js(r'''
searchData = {
  '10001': {
    shopware: {addresses: [
      {id: 'sw-billing', company: 'Beispiel GmbH', street: 'Rechnungsweg 1'},
      {id: 'sw-shipping', company: 'Beispiel GmbH', street: 'Lieferweg 2'},
    ]},
    django: {id: 71, addresses: [
      {id: 11, api_id: 'sw-billing', erp_ans_nr: 0, erp_asp_nr: 0, name1: 'Beispiel GmbH', street: 'Rechnungsweg 1'},
      {id: 12, api_id: 'sw-shipping', erp_ans_nr: 1, erp_asp_nr: 0, name1: 'Beispiel GmbH', street: 'Lieferweg 2'},
    ]},
    microtech: {addresses: [
      {ans_nr: 0, name1: 'Beispiel GmbH', street: 'Rechnungsweg 1', contacts: [
        {asp_nr: 0, first_name: 'Britta', last_name: 'Heidel'},
        {asp_nr: 1, first_name: 'Max', last_name: 'Mustermann'},
      ]},
      {ans_nr: 1, name1: 'Beispiel GmbH', street: 'Lieferweg 2', contacts: [
        {asp_nr: 0, first_name: 'Britta', last_name: 'Heidel'},
      ]},
    ]},
  },
};
const groups = addressComparisonGroups('10001');
assert.equal(groups.length, 2);
assert.equal(groups[0].detail, 'AnsNr 0');
assert.equal(groups[0].shopware[0].id, 'sw-billing');
assert.equal(groups[0].django[0].id, 11);
assert.equal(groups[0].microtech[0].contacts.length, 2);
const microtechHtml = comparisonAddressCard('10001', 'microtech', groups[0].microtech[0]);
assert.ok(microtechHtml.includes('Ansprechpartner (2)'));
assert.ok(microtechHtml.includes('Britta Heidel'));
assert.ok(microtechHtml.includes('Max Mustermann'));
assert.equal((microtechHtml.match(/microtech-number-pair/g) || []).length, 2);
assert.ok(microtechHtml.includes('microtech-number-value'));
assert.ok(microtechHtml.includes('AnspNr'));
const shopwareHtml = comparisonAddressCard('10001', 'shopware', groups[0].shopware[0]);
assert.ok(shopwareHtml.includes('comparison-address-copy'));
assert.ok(shopwareHtml.includes('adoptShopwareAddress'));
assert.ok(shopwareHtml.includes('arrow_forward'));
const comparisonHtml = renderComparisonRow('10001');
assert.ok(comparisonHtml.includes('comparison-matrix'));
assert.equal((comparisonHtml.match(/comparison-address-cell/g) || []).length, 6);
assert.ok(comparisonHtml.includes('Jede Zeile ist eine gemeinsame Zuordnung.'));
''')

    def test_modal_close_invalidates_preview_without_starting_merge(self):
        self.run_js(r'''
openShopwareMergeModal();
swMergePreview = {selection: swMergeSelection(), data: {previewToken: 'discard-me'}};
closeShopwareMergeModal();
assert.equal(elements.get('sw-merge-modal').open, false);
assert.equal(swMergePreview, null);
await executeShopwareMerge();
assert.equal(networkCalls.length, 0);
assert.equal(stored.size, 0);
''')

    def test_failed_or_incomplete_preview_never_enables_merge(self):
        self.run_js(r'''
swMergePreview = {selection: swMergeSelection(), data: {previewToken: 'old'}};
fetch = async () => ({ok: true, json: async () => ({sourceId: 'a'.repeat(32), targetId: 'b'.repeat(32)})});
await loadShopwareMergePreview();
assert.equal(swMergePreview, null);
assert.equal(elements.get('sw-merge-btn').disabled, true);
assert.equal(elements.get('sw-merge-modal').open, true);
assert.ok(elements.get('sw-merge-preview').innerHTML.includes('Vergleichsdaten fehlen'));
await executeShopwareMerge();
assert.equal(stored.size, 0);
''')

    def test_busy_modal_blocks_dismissal_but_pending_can_be_reopened(self):
        self.run_js(r'''
openShopwareMergeModal();
setShopwareMergeBusy(true);
let prevented = false;
elements.get('sw-merge-modal').listeners.cancel({preventDefault: () => {prevented = true;}});
closeShopwareMergeModal();
assert.equal(prevented, true);
assert.equal(elements.get('sw-merge-modal').open, true);
setShopwareMergeBusy(false);
swMergePending = {operation_id: 'c'.repeat(32)};
showShopwareMergePending('Ergebnis unbekannt');
closeShopwareMergeModal();
assert.ok(swMergePending);
await loadShopwareMergePreview();
assert.equal(elements.get('sw-merge-modal').open, true);
assert.ok(elements.get('sw-merge-result').innerHTML.includes('Ergebnis unbekannt'));
assert.equal(networkCalls.length, 0);
''')

    def test_status_mismatching_selected_default_keeps_recovery(self):
        self.run_js(r'''
swMergePending = {action: 'execute', ...swMergeSelection(), operation_id: 'c'.repeat(32),
  preview_token: 'x', default_billing_address_id: 'd'.repeat(32)};
stored.set(swMergeStorageKey, JSON.stringify(swMergePending));
fetch = async () => ({ok: true, json: async () => ({status: 'merged',
  operationId: 'c'.repeat(32), sourceId: 'a'.repeat(32), targetId: 'b'.repeat(32),
  defaultBillingAddressId: 'f'.repeat(32), defaultShippingAddressId: 'e'.repeat(32),
  addressesMoved: 5, ordersMoved: 1, credentialsCopied: true,
})});
await checkShopwareMergeStatus();
assert.ok(swMergePending);
assert.equal(stored.size, 1);
assert.ok(elements.get('sw-merge-result').innerHTML.includes('passt nicht'));
''')

    def test_page_entrypoint_does_not_expose_general_django_merge(self):
        template = (Path(__file__).resolve().parents[1] / "templates/admin/customer_merge.html").read_text()
        entrypoint = template.split("function renderMergeSection()", 1)[1].split("function renderDjangoMergeSection()", 1)[0]
        self.assertIn("renderShopwareMergeSection();", entrypoint)
        self.assertNotIn("renderDjangoMergeSection(", entrypoint)
        self.assertIn("document.getElementById('merge-section').innerHTML = '';", entrypoint)

    def test_stale_preview_requires_new_preview_and_confirmation(self):
        self.run_js(r'''
const selection = swMergeSelection();
openShopwareMergeModal();
swMergePreview = {selection, data: {sourceId: selection.delete_sw_id, targetId: selection.keep_sw_id,
  credentialsCopied: true, addressesMoved: 5, ordersMoved: 1, previewToken: 'stale'}};
fetch = async () => ({ok: false, json: async () => ({error: 'Neue Vorschau erforderlich.',
  code: 'GC_MERGE_PREVIEW_STALE', uncertain: false})});
await executeShopwareMerge();
assert.equal(swMergePending, null);
assert.equal(swMergePreview, null);
assert.equal(stored.size, 0);
assert.equal(elements.get('sw-merge-btn').disabled, true);
assert.ok(elements.get('sw-merge-result').innerHTML.includes('erneut bestätigen'));
const confirms = getConfirmCount();
await executeShopwareMerge();
assert.equal(getConfirmCount(), confirms, 'No re-execution without a new authoritative preview');
''')

    def test_successful_status_clears_pending_and_rejects_other_target(self):
        self.run_js(r'''
swMergePending = {action: 'execute', ...swMergeSelection(), operation_id: 'c'.repeat(32), preview_token: 'x'};
stored.set(swMergeStorageKey, JSON.stringify(swMergePending));
assert.throws(() => completeShopwareMerge({operationId: swMergePending.operation_id,
  sourceId: swMergePending.delete_sw_id, targetId: 'f'.repeat(32)}));
assert.ok(swMergePending, 'Mismatch must retain the original operation for recovery');
completeShopwareMerge({operationId: swMergePending.operation_id, sourceId: swMergePending.delete_sw_id,
  targetId: swMergePending.keep_sw_id, addressesMoved: 5, ordersMoved: 501, credentialsCopied: true});
assert.equal(swMergePending, null);
assert.equal(stored.size, 0);
assert.ok(elements.get('sw-merge-result').innerHTML.includes('Passwort-Hash wurden gemeinsam'));
''')


class ShopwareCustomerAddressDeleteTest(SimpleTestCase):
    @patch("shopware.services.CustomerService")
    def test_default_addresses_are_not_deleted(self, customer_service_class):
        service = customer_service_class.return_value
        service.get_by_id.return_value = {
            "data": [{
                "id": "customer-id",
                "attributes": {
                    "defaultBillingAddressId": "billing-id",
                    "addresses": [{"id": "billing-id"}, {"id": "other-id"}],
                },
            }]
        }

        with self.assertRaisesMessage(ValueError, "Standard-Liefer"):
            ShopwareCustomerAddressService().delete_addresses(
                customer_id="customer-id", address_ids=["billing-id"]
            )

        service.request_delete.assert_not_called()
