from django.test import TestCase

from customer.models import Customer
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
