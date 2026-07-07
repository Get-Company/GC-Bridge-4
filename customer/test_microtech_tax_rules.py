from django.test import SimpleTestCase

from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService


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
