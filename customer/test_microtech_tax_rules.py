from django.test import SimpleTestCase

from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
from customer.services.webshop_mapping import CustomerWebshopMappingService


class MicrotechCustomerTaxRuleTest(SimpleTestCase):
    def test_eu_customer_with_vat_id_is_tax_free(self):
        self.assertEqual(CustomerUpsertMicrotechService._resolve_ustkat("AT", "ATU12345678"), 3)

    def test_eu_customer_without_vat_id_is_taxed(self):
        self.assertEqual(CustomerUpsertMicrotechService._resolve_ustkat("AT", ""), 1)

    def test_germany_is_taxed_even_with_vat_id(self):
        self.assertEqual(CustomerUpsertMicrotechService._resolve_ustkat("DE", "DE123456789"), 1)

    def test_customer_input_contains_vat_id_for_microtech_tax_rule(self):
        customer = Customer(
            erp_nr="100001",
            name="AT Firma",
            email="office@example.test",
            vat_id="ATU12345678",
        )
        address = Address(
            customer=customer,
            name1="AT Firma",
            country_code="AT",
            city="Wien",
        )

        payload = CustomerUpsertMicrotechService()._build_customer_input(customer=customer, address=address)

        self.assertEqual(payload["country"], "AT")
        self.assertEqual(payload["vatId"], "ATU12345678")

    def test_customer_input_uses_webshop_default_mapping(self):
        customer = Customer(erp_nr="100001", name="Beispiel AG")
        address = Address(customer=customer, name1="Beispiel AG", country_code="CH")

        payload = CustomerUpsertMicrotechService()._build_customer_input(customer=customer, address=address)

        self.assertEqual(payload["microtechFields"]["Status"], "Webshop-Kunde")
        self.assertEqual(payload["microtechFields"]["SuchBeg"], "CL")
        self.assertEqual(payload["microtechFields"]["VsdArt"], 10)

    def test_german_customer_uses_german_webshop_mapping(self):
        values = CustomerWebshopMappingService().get_microtech_defaults(country_code="DE")

        self.assertEqual(values["Status"], "Webshop-Kunde")
        self.assertNotIn("SuchBeg", values)

    def test_na1_uses_company_name_or_german_salutation(self):
        service = CustomerUpsertMicrotechService()

        company_name = service._resolve_na1_for_anschrift(
            address=Address(name1="Beispiel GmbH", title="Herr"),
            na1_mode="firma_or_salutation",
        )
        private_salutation = service._resolve_na1_for_anschrift(
            address=Address(name1="Herr", title="Herr"),
            na1_mode="firma_or_salutation",
        )

        self.assertEqual(company_name, "Beispiel GmbH")
        self.assertEqual(private_salutation, "Herr")
