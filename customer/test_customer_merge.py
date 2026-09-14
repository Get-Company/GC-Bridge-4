from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from customer.services.customer_merge import (
    CustomerMergeSearchService,
    ShopwareCustomerMergeService,
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
                        "contacts": [
                            {
                                "isDefault": True,
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
    def _merge(self, sw_service, *, keep, delete, order_service=None):
        patches = [
            patch("shopware.services.CustomerService", return_value=sw_service),
            patch.object(ShopwareCustomerMergeService, "_reconcile_django_api_id"),
        ]
        if order_service is None:
            patches.append(
                patch.object(ShopwareCustomerMergeService, "_move_orders", return_value=(0, []))
            )
        else:
            patches.append(patch("shopware.services.OrderService", return_value=order_service))
        started = [p.start() for p in patches]
        try:
            return ShopwareCustomerMergeService().merge(keep_sw_id=keep, delete_sw_id=delete)
        finally:
            for p in patches:
                p.stop()

    def test_identical_ids_raise(self):
        with self.assertRaises(ValueError):
            ShopwareCustomerMergeService().merge(keep_sw_id="same", delete_sw_id="same")

    def test_missing_customer_raises(self):
        sw = MagicMock()
        sw.get_by_id.side_effect = lambda cid: {"data": []}
        with self.assertRaises(ValueError):
            self._merge(sw, keep="keep-id", delete="del-id")

    def test_keep_survives_when_it_has_the_newer_login(self):
        sw = MagicMock()
        payloads = {
            "keep-id": _sw_customer("keep-id", "1001", "keep@x.de", last_login="2026-02-01T10:00:00"),
            "del-id": _sw_customer("del-id", "1002", "del@x.de", last_login="2026-01-01T10:00:00"),
        }
        sw.get_by_id.side_effect = lambda cid: payloads[cid]

        result = self._merge(sw, keep="keep-id", delete="del-id")

        self.assertEqual(result["survivor_sw_id"], "keep-id")
        self.assertEqual(result["removed_sw_id"], "del-id")
        self.assertFalse(result["identity_transplanted"])
        sw.request_delete.assert_called_once_with("/customer/del-id")
        sw.update_customer.assert_not_called()

    def test_delete_survives_and_keep_identity_is_transplanted(self):
        sw = MagicMock()
        payloads = {
            "keep-id": _sw_customer(
                "keep-id", "1001", "keep@x.de",
                last_login="2026-01-01T10:00:00", first_name="Right", last_name="Customer",
            ),
            "del-id": _sw_customer("del-id", "1002", "del@x.de", last_login="2026-02-01T10:00:00"),
        }
        sw.get_by_id.side_effect = lambda cid: payloads[cid]

        result = self._merge(sw, keep="keep-id", delete="del-id")

        # The last-login record (del-id) survives and keeps its own credentials.
        self.assertEqual(result["survivor_sw_id"], "del-id")
        self.assertEqual(result["removed_sw_id"], "keep-id")
        self.assertTrue(result["identity_transplanted"])
        # The keep record is deleted, then the keep identity is written onto the survivor.
        sw.request_delete.assert_called_once_with("/customer/keep-id")
        sw.update_customer.assert_called_once()
        called_id, payload = sw.update_customer.call_args.args
        self.assertEqual(called_id, "del-id")
        self.assertEqual(payload["customerNumber"], "1001")
        self.assertEqual(payload["firstName"], "Right")
        # Email must never be transplanted — it stays with the surviving login.
        self.assertNotIn("email", payload)

    def test_no_logins_keeps_user_choice(self):
        sw = MagicMock()
        sw.get_by_id.side_effect = lambda cid: _sw_customer(cid, cid, f"{cid}@x.de")

        result = self._merge(sw, keep="keep-id", delete="del-id")

        self.assertEqual(result["survivor_sw_id"], "keep-id")
        sw.request_delete.assert_called_once_with("/customer/del-id")

    def test_orders_are_moved_from_removed_to_survivor(self):
        sw = MagicMock()
        sw.get_by_id.side_effect = lambda cid: _sw_customer(cid, cid, f"{cid}@x.de")
        order_service = MagicMock()
        order_service.request_post.return_value = {
            "data": [{"id": "o1", "orderCustomer": {"id": "oc1"}}]
        }

        result = self._merge(sw, keep="keep-id", delete="del-id", order_service=order_service)

        self.assertEqual(result["orders_moved"], 1)
        order_service.request_patch.assert_called_once_with(
            "/order-customer/oc1", payload={"customerId": "keep-id"}
        )
