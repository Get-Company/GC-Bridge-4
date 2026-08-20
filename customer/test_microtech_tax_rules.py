from django.test import SimpleTestCase

from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
from customer.services.webshop_mapping import CustomerWebshopMappingService


class MicrotechCustomerTaxRuleTest(SimpleTestCase):
    def test_tax_category_uses_the_confirmed_country_group_and_vat_rules(self):
        resolve = CustomerUpsertMicrotechService._resolve_ustkat

        self.assertEqual(resolve("DE", "DE123456789", "GC | Italien Firma B2B"), 1)
        self.assertEqual(resolve("CH", "CHE123", "GC | Schweiz Firma B2B"), 2)
        self.assertEqual(resolve("US", "US123", "Standard-Kundengruppe"), 2)
        self.assertEqual(resolve("AT", "ATU12345678", "GC | Italien Firma B2B"), 3)
        self.assertEqual(resolve("AT", "", "GC | Italien Firma B2B"), 1)
        self.assertEqual(resolve("AT", "ATU12345678", "Standard-Kundengruppe"), 1)

    def test_customer_input_contains_vat_id_for_microtech_tax_rule(self):
        customer = Customer(
            erp_nr="100001",
            name="AT Firma",
            email="office@example.test",
            vat_id="ATU12345678",
            shopware_customer_group="GC | Italien Firma B2B",
        )
        shipping_address = Address(
            customer=customer,
            name1="AT Firma",
            country_code="CH",
            city="Wien",
        )
        billing_address = Address(customer=customer, name1="AT Firma", country_code="AT", city="Wien")

        payload = CustomerUpsertMicrotechService()._build_customer_input(
            customer=customer,
            address=shipping_address,
            billing_address=billing_address,
        )

        self.assertEqual(payload["country"], "CH")
        self.assertEqual(payload["vatId"], "ATU12345678")
        self.assertEqual(payload["taxCategory"], 3)

    def test_customer_input_uses_webshop_default_mapping(self):
        customer = Customer(erp_nr="100001", name="Beispiel AG")
        address = Address(customer=customer, name1="Beispiel AG", country_code="CH")

        payload = CustomerUpsertMicrotechService()._build_customer_input(customer=customer, address=address)

        self.assertEqual(payload["webshopDefaults"]["Status"], "Webshop-Kunde")
        self.assertEqual(payload["webshopDefaults"]["SuchBeg"], "CL")
        self.assertEqual(payload["webshopDefaults"]["VsdArt"], 10)
        self.assertEqual(
            {
                field: payload["webshopDefaults"][field]
                for field in ("TextKz1", "TextKz2", "TextKz3", "TextKz4", "TextKz5")
            },
            {"TextKz1": 1, "TextKz2": 0, "TextKz3": 0, "TextKz4": 0, "TextKz5": 0},
        )

    def test_german_customer_uses_german_webshop_mapping(self):
        values = CustomerWebshopMappingService().get_microtech_defaults(country_code="DE")

        self.assertEqual(values["Status"], "Webshop-Kunde")
        self.assertNotIn("SuchBeg", values)

    def test_postal_address_mapping_uses_company_name_or_german_salutation(self):
        mapping_service = CustomerWebshopMappingService()
        upsert_service = CustomerUpsertMicrotechService()

        company_address = Address(
            name1="Beispiel GmbH",
            name2="Max Muster",
            title="Herr",
            first_name="Max",
            last_name="Muster",
        )
        private_address = Address(
            name1="Herr",
            name2="Max Muster",
            title="Herr",
            first_name="Max",
            last_name="Muster",
            email="privat@example.test",
        )

        company_name = mapping_service.get_postal_address_mapping(address=company_address)["name1"]
        private_salutation = mapping_service.get_postal_address_mapping(address=private_address)["name1"]

        self.assertEqual(company_name, "Firma")
        self.assertEqual(private_salutation, "Herr")
        self.assertEqual(
            mapping_service.get_postal_address_mapping(address=company_address)["name2"],
            "Beispiel GmbH",
        )
        self.assertEqual(
            mapping_service.get_postal_address_mapping(address=private_address)["name2"],
            "Max Muster",
        )
        self.assertEqual(
            upsert_service._build_postal_address_input(
                address=company_address,
                is_shipping=True,
                is_invoice=True,
                na1_mode="auto",
                na1_static_value="",
            )["name1"],
            "Firma",
        )
        self.assertEqual(
            upsert_service._build_postal_address_input(
                address=private_address,
                is_shipping=True,
                is_invoice=True,
                na1_mode="auto",
                na1_static_value="",
            )["name1"],
            "Herr",
        )
        self.assertEqual(
            upsert_service._build_postal_address_input(
                address=company_address,
                is_shipping=True,
                is_invoice=True,
                na1_mode="auto",
                na1_static_value="",
            )["name2"],
            "Beispiel GmbH",
        )

    def test_email_and_salutation_mapping_uses_the_address_role(self):
        address = Address(
            name1="Herr",
            name2="Max Muster",
            title="Herr",
            first_name="Max",
            last_name="Muster",
            email="max@example.test",
        )
        service = CustomerUpsertMicrotechService()

        delivery_payload = service._build_postal_address_input(
            address=address,
            is_shipping=True,
            is_invoice=False,
            na1_mode="auto",
            na1_static_value="",
            include_email=True,
        )
        invoice_payload = service._build_postal_address_input(
            address=address,
            is_shipping=False,
            is_invoice=True,
            na1_mode="auto",
            na1_static_value="",
            include_email=False,
        )
        contact_payload = service._build_contact_person_input(address=address)

        self.assertEqual(delivery_payload["email"], "max@example.test")
        self.assertNotIn("email", invoice_payload)
        self.assertEqual(contact_payload["email"], "max@example.test")
        self.assertEqual(contact_payload["salutation"], "Herrn")
        self.assertEqual(contact_payload["displayName"], "Herrn Max Muster")
