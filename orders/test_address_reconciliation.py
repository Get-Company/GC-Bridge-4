from unittest.mock import patch

from django.test import SimpleTestCase

from customer.models import Address, Customer
from orders.models import Order
from orders.services.order_address_reconciliation import OrderAddressReconciliationService


class PostData(dict):
    def getlist(self, key):
        value = self.get(key, [])
        return value if isinstance(value, list) else [value]


class FakeMicrotechClient:
    def __init__(self):
        self.postal_updates = []
        self.contact_updates = []

    def request_customer(self, customer_number):
        return {
            "customer": {
                "customerNumber": customer_number,
                "erpAddressNumber": 4711,
                "addresses": [
                    {
                        "addressNumber": 4711,
                        "addressSubNumber": 3,
                        "name1": "Muster GmbH",
                        "street": "Hauptstraße 10",
                        "zipCode": "80331",
                        "city": "München",
                        "country": "DE",
                        "contacts": [
                            {
                                "contactNumber": 5,
                                "salutation": "Herr",
                                "firstName": "Max",
                                "lastName": "Mustermann",
                                "email": "max@example.test",
                            }
                        ],
                    },
                    {
                        "addressNumber": 4711,
                        "addressSubNumber": 4,
                        "name1": "Lager",
                        "street": "Lagerweg 1",
                        "zipCode": "80333",
                        "city": "München",
                        "country": "DE",
                        "contacts": [],
                    },
                ],
            }
        }

    def update_postal_address(self, address_number, address_sub_number, input_data):
        self.postal_updates.append((address_number, address_sub_number, input_data))

    def update_contact_person(self, address_number, address_sub_number, contact_number, input_data):
        self.contact_updates.append((address_number, address_sub_number, contact_number, input_data))


class OrderAddressReconciliationServiceTest(SimpleTestCase):
    def setUp(self):
        self.customer = Customer(erp_nr="4711", name="Muster GmbH")
        self.address = Address(
            customer=self.customer,
            name1="Muster GmbH",
            street="Neue Straße 12",
            postal_code="80331",
            city="München",
            country_code="DE",
            email="shop@example.test",
            first_name="Max",
            last_name="Mustermann",
        )
        self.order = Order(
            api_id="reconciliation-order",
            customer=self.customer,
            shipping_address=self.address,
            billing_address=self.address,
        )
        self.service = OrderAddressReconciliationService()
        self.client = FakeMicrotechClient()

    def test_comparison_loads_microtech_candidates_for_same_shipping_and_billing_address(self):
        comparison = self.service.get_comparison(order=self.order, client=self.client)

        self.assertEqual(comparison["address_number"], 4711)
        self.assertEqual(len(comparison["scopes"]), 1)
        self.assertEqual(comparison["scopes"][0]["label"], "Liefer- und Rechnungsanschrift")
        self.assertEqual(comparison["scopes"][0]["candidates"][0]["address_sub_number"], 3)
        self.assertEqual(comparison["scopes"][0]["candidates"][0]["contacts"][0]["contact_number"], 5)

    def test_comparison_keeps_shipping_and_billing_addresses_separate(self):
        billing_address = Address(
            customer=self.customer,
            name1="Muster GmbH",
            street="Rechnungsweg 2",
            postal_code="80333",
            city="München",
            country_code="DE",
        )
        self.order.billing_address = billing_address

        comparison = self.service.get_comparison(order=self.order, client=self.client)

        self.assertEqual([scope["key"] for scope in comparison["scopes"]], ["shipping", "billing"])

    @patch("orders.services.order_address_reconciliation.transaction.atomic")
    @patch.object(Address, "save")
    def test_apply_updates_only_selected_fields_and_persists_existing_ids(self, mock_save, mock_atomic):
        comparison = self.service.get_comparison(order=self.order, client=self.client)
        post_data = PostData(
            {
                "shipping_billing_address_sub_number": "3",
                "shipping_billing_contact_reference": "3:5",
                "shipping_billing_fields": ["postal:name1", "contact:first_name"],
            }
        )

        updates = self.service.apply_from_post_data(
            comparison=comparison,
            post_data=post_data,
            client=self.client,
        )

        self.assertEqual(updates[0]["address_sub_number"], 3)
        self.assertEqual(self.client.postal_updates, [(4711, 3, {"name1": "Muster GmbH"})])
        self.assertEqual(self.client.contact_updates, [(4711, 3, 5, {"firstName": "Max"})])
        self.assertEqual(self.address.erp_nr, 4711)
        self.assertEqual(self.address.erp_ans_nr, 3)
        self.assertEqual(self.address.erp_asp_nr, 5)
        mock_save.assert_called_once()

    def test_apply_rejects_contact_from_another_microtech_address(self):
        comparison = self.service.get_comparison(order=self.order, client=self.client)
        post_data = PostData(
            {
                "shipping_billing_address_sub_number": "3",
                "shipping_billing_contact_reference": "4:5",
            }
        )

        with self.assertRaisesMessage(ValueError, "Ansprechpartner gehört nicht zur gewählten Anschrift"):
            self.service.apply_from_post_data(comparison=comparison, post_data=post_data, client=self.client)

    def test_comparison_keeps_zero_as_a_valid_microtech_address_number(self):
        response = self.client.request_customer("4711")
        response["customer"]["addresses"][0]["addressSubNumber"] = 0
        self.client.request_customer = lambda _customer_number: response

        comparison = self.service.get_comparison(order=self.order, client=self.client)

        self.assertEqual(comparison["scopes"][0]["candidates"][0]["address_sub_number"], 0)
