from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db.models.deletion import RestrictedError
from django.test import SimpleTestCase, TestCase

from customer.models import Address, Customer
from orders.models import Order
from orders.services.order_address_backfill import OrderAddressBackfillService
from shopware.services import OrderService


class OrderAddressSnapshotFetchTest(SimpleTestCase):
    @patch.object(OrderService, "request_post")
    def test_fetches_both_order_address_snapshots_and_order_customer(self, request_post):
        OrderService().get_with_addresses_by_id("b" * 32)

        criteria = request_post.call_args.kwargs["payload"]
        self.assertIn("billingAddress", criteria.associations)
        self.assertIn("shippingOrderAddress", criteria.associations["deliveries"].associations)
        self.assertIn("orderCustomer", criteria.associations)


class OrderAddressBackfillTest(SimpleTestCase):
    def setUp(self):
        self.customer = SimpleNamespace(pk=7, api_id="a" * 32)
        self.order = SimpleNamespace(
            pk=9, api_id="b" * 32, order_number="10390",
            billing_address_id=None, shipping_address_id=None,
        )
        self.address = SimpleNamespace(pk=1035)
        self.snapshot = {
            "street": "Henry-Dunant-Straße, 1", "zipcode": "64521",
            "city": "Groß-Gerau", "company": "DRK Kreisverband Groß-Gerau e.V.",
            "firstName": "Tanja", "lastName": "Blum",
        }
        self.customer_address = {"id": "c" * 32, **self.snapshot}

    def _services(self, customer_lookup, order_lookup, shopware_customer, shopware_order):
        customer_lookup.return_value.first.return_value = self.customer
        pending = MagicMock()
        pending.filter.return_value.exclude.return_value = [self.order]
        update = MagicMock()
        update.update.return_value = 1
        order_lookup.side_effect = [pending, update, update]
        shopware_customer.return_value.get_by_id.return_value = {
            "data": [{"id": self.customer.api_id, "addresses": [self.customer_address]}],
        }
        shopware_order.return_value.get_with_addresses_by_id.return_value = {
            "data": [{
                "id": self.order.api_id,
                "orderCustomer": {"customerId": self.customer.api_id},
                "billingAddress": self.snapshot,
                "deliveries": [{"shippingOrderAddress": self.snapshot}],
            }],
        }

    @patch("orders.services.order_sync.Address.objects.filter")
    @patch("orders.services.order_address_backfill.OrderService")
    @patch("orders.services.order_address_backfill.CustomerService")
    @patch("orders.services.order_address_backfill.Order.objects.filter")
    @patch("orders.services.order_address_backfill.Customer.objects.filter")
    def test_links_only_missing_fields_to_exact_mapped_address(
        self, customer_lookup, order_lookup, shopware_customer, shopware_order, addresses,
    ):
        self._services(customer_lookup, order_lookup, shopware_customer, shopware_order)
        addresses.return_value.first.return_value = self.address

        result = OrderAddressBackfillService().reconcile_customer(customer_id=7, address_id=1035)

        self.assertEqual(result["orders_linked"], 1)
        self.assertEqual(result["addresses_linked"], 2)
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(order_lookup.call_count, 3)
        self.assertEqual(order_lookup.call_args_list[1].kwargs["billing_address__isnull"], True)
        self.assertEqual(order_lookup.call_args_list[2].kwargs["shipping_address__isnull"], True)

    @patch("orders.services.order_sync.Address.objects.filter")
    @patch("orders.services.order_address_backfill.OrderService")
    @patch("orders.services.order_address_backfill.CustomerService")
    @patch("orders.services.order_address_backfill.Order.objects.filter")
    @patch("orders.services.order_address_backfill.Customer.objects.filter")
    def test_does_not_guess_when_order_snapshot_differs(
        self, customer_lookup, order_lookup, shopware_customer, shopware_order, addresses,
    ):
        self._services(customer_lookup, order_lookup, shopware_customer, shopware_order)
        shopware_order.return_value.get_with_addresses_by_id.return_value["data"][0][
            "billingAddress"
        ] = {**self.snapshot, "company": "Andere Gesellschaft"}
        shopware_order.return_value.get_with_addresses_by_id.return_value["data"][0][
            "deliveries"
        ] = [{"shippingOrderAddress": {**self.snapshot, "company": "Andere Gesellschaft"}}]

        result = OrderAddressBackfillService().reconcile_customer(customer_id=7, address_id=1035)

        self.assertEqual(result["addresses_linked"], 0)
        self.assertEqual(result["unresolved"], ["10390"])
        addresses.assert_not_called()
        order_lookup.assert_called_once()

    @patch("orders.services.order_sync.Address.objects.filter")
    @patch("orders.services.order_address_backfill.OrderService")
    @patch("orders.services.order_address_backfill.CustomerService")
    @patch("orders.services.order_address_backfill.Order.objects.filter")
    @patch("orders.services.order_address_backfill.Customer.objects.filter")
    def test_does_not_link_another_address_of_the_same_customer(
        self, customer_lookup, order_lookup, shopware_customer, shopware_order, addresses,
    ):
        self._services(customer_lookup, order_lookup, shopware_customer, shopware_order)
        addresses.return_value.first.return_value = SimpleNamespace(pk=1032)

        result = OrderAddressBackfillService().reconcile_customer(customer_id=7, address_id=1035)

        self.assertEqual(result["addresses_linked"], 0)
        self.assertEqual(result["unresolved"], ["10390"])
        order_lookup.assert_called_once()

    @patch("orders.services.order_address_backfill.OrderService")
    @patch("orders.services.order_address_backfill.CustomerService")
    @patch("orders.services.order_address_backfill.Order.objects.filter")
    @patch("orders.services.order_address_backfill.Customer.objects.filter")
    def test_rejects_order_linked_to_another_shopware_customer(
        self, customer_lookup, order_lookup, shopware_customer, shopware_order,
    ):
        self._services(customer_lookup, order_lookup, shopware_customer, shopware_order)
        shopware_order.return_value.get_with_addresses_by_id.return_value["data"][0][
            "orderCustomer"
        ] = {"customerId": "d" * 32}

        result = OrderAddressBackfillService().reconcile_customer(customer_id=7, address_id=1035)

        self.assertEqual(result["addresses_linked"], 0)
        self.assertEqual(result["unresolved"], ["10390"])
        order_lookup.assert_called_once()


class OrderAddressDeletionGuardTest(TestCase):
    def test_referenced_address_cannot_be_deleted(self):
        customer = Customer.objects.create(erp_nr="56863")
        address = Address.objects.create(customer=customer, api_id="c" * 32)
        Order.objects.create(
            api_id="b" * 32, customer=customer,
            billing_address=address, shipping_address=address,
        )

        with self.assertRaises(RestrictedError):
            address.delete()

        self.assertTrue(Address.objects.filter(pk=address.pk).exists())
