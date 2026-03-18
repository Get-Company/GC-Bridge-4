from unittest.mock import MagicMock, call

from django.test import TestCase

from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
from orders.services.order_sync import OrderSyncService


class ShopwarePhoneToDjangoAddressTest(TestCase):
    def test_order_sync_upserts_phone_number_into_address(self):
        customer = Customer.objects.create(
            erp_nr="1000",
            email="kunde@example.com",
        )

        address = OrderSyncService()._upsert_address(
            customer=customer,
            address_data={
                "id": "addr-1",
                "firstName": "Max",
                "lastName": "Mustermann",
                "street": "Musterstrasse 7",
                "zipcode": "83250",
                "city": "Marquartstein",
                "phoneNumber": "+49 8641 975911",
                "country": {"iso": "DE"},
                "salutation": {"displayName": "Herr"},
            },
            fallback_email=customer.email,
            is_invoice=True,
            is_shipping=True,
        )

        self.assertEqual(address.phone, "+49 8641 975911")


class DjangoPhoneToMicrotechTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            erp_nr="1000",
            email="kunde@example.com",
            vat_id="DE123456789",
        )
        self.address = Address.objects.create(
            customer=self.customer,
            name1="ACME GmbH",
            name2="ACME GmbH",
            first_name="Max",
            last_name="Mustermann",
            title="Herr",
            email="versand@example.com",
            phone="+49 8641 975911",
            street="Musterstrasse 7",
            postal_code="83250",
            city="Marquartstein",
            country_code="DE",
            is_shipping=True,
            is_invoice=True,
        )
        self.service = CustomerUpsertMicrotechService()

    def test_upsert_adresse_record_writes_phone_to_microtech_adressen(self):
        adresse_service = MagicMock()
        adresse_service.find.return_value = True

        erp_nr, is_new_customer = self.service._upsert_adresse_record(
            customer=self.customer,
            shipping=self.address,
            adresse_service=adresse_service,
        )

        self.assertEqual(erp_nr, "1000")
        self.assertFalse(is_new_customer)
        adresse_service.set_field.assert_has_calls(
            [
                call("Status", "GC-SW6 Webshop Kunde"),
                call("EMail1", "versand@example.com"),
                call("Tel", "+49 8641 975911"),
                call("UStIdNr", "DE123456789"),
                call("UStKat", 1),
            ]
        )

    def test_upsert_anschrift_and_ansprechpartner_write_phone(self):
        anschrift_service = MagicMock()
        ansprechpartner_service = MagicMock()

        self.service._map_anschrift_fields(
            erp_nr="1000",
            address=self.address,
            is_shipping=True,
            is_invoice=True,
            anschrift_service=anschrift_service,
            na1_mode="auto",
            na1_static_value="",
        )
        self.service._map_ansprechpartner_fields(
            erp_nr="1000",
            ans_nr=1,
            address=self.address,
            ansprechpartner_service=ansprechpartner_service,
        )

        anschrift_service.set_field.assert_any_call("Tel", "+49 8641 975911")
        ansprechpartner_service.set_field.assert_any_call("Tel1", "+49 8641 975911")
