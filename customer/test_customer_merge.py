from django.test import SimpleTestCase

from customer.services.customer_merge import CustomerMergeSearchService


class CustomerMergeMicrotechSearchTest(SimpleTestCase):
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

    def test_structured_search_uses_email_and_full_name_filters(self):
        requests = dict(
            CustomerMergeSearchService._microtech_field_resolution_requests(
                email="max@example.com",
                first_name="Max",
                last_name="Muster",
            )
        )

        self.assertEqual(requests["email_adresse"]["dataset"], "Adressen")
        self.assertEqual(requests["email_adresse"]["indexField"], "Nr")
        self.assertEqual(requests["email_adresse"]["filter"], "EMail1 = 'max@example.com'")
        self.assertEqual(requests["email_ansprechpartner"]["dataset"], "Ansprechpartner")
        self.assertEqual(requests["kundenname"]["indexField"], "NNa")
        self.assertEqual(requests["kundenname"]["filter"], "VNa = 'Max'")
        self.assertEqual(requests["kundenname"]["range"]["fromValues"], ["Muster", ""])

    def test_structured_first_name_filter_escapes_microtech_filter_quotes(self):
        requests = dict(
            CustomerMergeSearchService._microtech_field_resolution_requests(first_name="O'Brien")
        )

        self.assertEqual(requests["vorname"]["filter"], "VNa = 'O''Brien'")

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
