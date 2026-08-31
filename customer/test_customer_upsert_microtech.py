from django.test import TestCase

from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService


class _FakeMicrotechClient:
    def __init__(self):
        self.update_postal_calls = []
        self.create_postal_calls = []
        self.update_customer_calls = []

    def request_customer(self, _erp_nr):
        return {
            "customer": {
                "customerNumber": "54346",
                "erpAddressNumber": 54346,
                "defaultShippingAddressNumber": 1,
                "defaultBillingAddressNumber": 1,
                "addresses": [
                    {
                        "addressSubNumber": 1,
                        "isDefaultShipping": True,
                        "isDefaultBilling": True,
                    }
                ],
            }
        }

    def update_customer(self, customer_number, input_data):
        self.update_customer_calls.append((customer_number, input_data))
        return {"customer": {"customerNumber": customer_number}}

    def update_postal_address(self, address_number, address_sub_number, input_data):
        self.update_postal_calls.append((address_number, address_sub_number, input_data))
        return {"postalAddress": {"addressNumber": address_number, "addressSubNumber": address_sub_number}}

    def create_postal_address(self, address_number, input_data):
        self.create_postal_calls.append((address_number, input_data))
        return {"postalAddress": {"addressNumber": address_number, "addressSubNumber": 3}}

    @staticmethod
    def create_contact_person(address_number, address_sub_number, _input_data):
        return {
            "contactPerson": {
                "addressNumber": address_number,
                "addressSubNumber": address_sub_number,
                "contactNumber": 1,
            }
        }

    @staticmethod
    def update_contact_person(address_number, address_sub_number, contact_number, _input_data):
        return {
            "contactPerson": {
                "addressNumber": address_number,
                "addressSubNumber": address_sub_number,
                "contactNumber": contact_number,
            }
        }


class CustomerUpsertMicrotechServiceTest(TestCase):
    def test_stale_ans_nr_creates_a_new_postal_address_and_preserves_no_false_ans_id(self):
        customer = Customer.objects.create(erp_nr="54346", name="Testkunde")
        address = Address.objects.create(
            customer=customer,
            erp_nr=54346,
            erp_ans_id=99,
            erp_ans_nr=2,
            erp_asp_id=5,
            erp_asp_nr=5,
            first_name="Max",
            last_name="Mustermann",
            country_code="DE",
            is_shipping=True,
            is_invoice=True,
        )
        client = _FakeMicrotechClient()

        result = CustomerUpsertMicrotechService()._upsert_customer_graphql(
            customer=customer,
            shipping=address,
            billing=address,
            na1_mode="auto",
            na1_static_value="",
            client=client,
        )

        address.refresh_from_db()
        self.assertEqual(result.shipping_ans_nr, 3)
        self.assertEqual(result.billing_ans_nr, 3)
        self.assertEqual(client.create_postal_calls[0][0], 54346)
        self.assertFalse(any(call[1] == 2 for call in client.update_postal_calls))
        self.assertIsNone(address.erp_combined_id)
        self.assertIsNone(address.erp_ans_id)
        self.assertEqual(address.erp_ans_nr, 3)
        self.assertEqual(
            client.update_customer_calls[-1],
            (
                "54346",
                {"defaultShippingAddressNumber": 3, "defaultBillingAddressNumber": 3},
            ),
        )
