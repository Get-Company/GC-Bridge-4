from django.test import SimpleTestCase

from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService


class MicrotechCustomerTaxRuleTest(SimpleTestCase):
    def test_eu_customer_with_vat_id_is_tax_free(self):
        self.assertEqual(CustomerUpsertMicrotechService._resolve_ustkat("AT", "ATU12345678"), 3)

    def test_eu_customer_without_vat_id_is_taxed(self):
        self.assertEqual(CustomerUpsertMicrotechService._resolve_ustkat("AT", ""), 1)

    def test_germany_is_taxed_even_with_vat_id(self):
        self.assertEqual(CustomerUpsertMicrotechService._resolve_ustkat("DE", "DE123456789"), 1)
