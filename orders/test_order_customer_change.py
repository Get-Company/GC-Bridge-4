from unittest.mock import MagicMock, patch

from django.test import TestCase

from customer.models import Address, Customer
from microtech.models import MicrotechGraphQLJob
from orders.models import Order
from orders.services.order_customer_change import (
    CONTEXT_SOURCE,
    OrderCustomerChangeService,
)


class OrderCustomerChangeServiceTest(TestCase):
    def setUp(self):
        customer = Customer.objects.create(erp_nr="10001", name="Alter Kunde")
        address = Address.objects.create(customer=customer, is_shipping=True, is_invoice=True)
        self.order = Order.objects.create(
            api_id="order-customer-change",
            order_number="1000",
            customer=customer,
            shipping_address=address,
            billing_address=address,
        )

    @patch("orders.services.order_customer_change.MicrotechGraphQLClientService")
    @patch("orders.services.order_customer_change.MicrotechJobSentinelService.submit_wrapper_job")
    def test_request_change_queues_a_customer_read_job(self, mock_submit, mock_client_class):
        mock_client_class.return_value.submit_request_customer.return_value = ("remote-job", 30)

        def submit_wrapper(**kwargs):
            kwargs["submit"]()
            return MagicMock(pk=42)

        mock_submit.side_effect = submit_wrapper

        job = OrderCustomerChangeService().request_change(order=self.order, erp_nr="20002")

        self.assertEqual(job.pk, 42)
        mock_client_class.return_value.submit_request_customer.assert_called_once_with("20002")
        call = mock_submit.call_args.kwargs
        self.assertEqual(call["context"], {"source": CONTEXT_SOURCE, "order_id": self.order.pk, "erp_nr": "20002"})
        self.assertEqual(call["request_payload"], {"customerNumber": "20002"})
        self.assertFalse(call["delete_after_completion"])

    def test_apply_result_replaces_customer_and_order_addresses(self):
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_READ,
            operation="requestCustomer",
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            context={"source": CONTEXT_SOURCE, "order_id": self.order.pk, "erp_nr": "20002"},
            result_payload={
                "data": {
                    "customerJob": {
                        "customer": {
                            "customerNumber": "20002",
                            "erpAddressNumber": 20002,
                            "name1": "Neuer Kunde GmbH",
                            "email": "neu@example.com",
                            "defaultShippingAddressNumber": 1,
                            "defaultBillingAddressNumber": 2,
                            "addresses": [
                                {
                                    "addressSubNumber": 1,
                                    "isDefaultShipping": True,
                                    "name1": "Lager",
                                    "street": "Lieferweg 1",
                                    "zipCode": "12345",
                                    "city": "Berlin",
                                    "country": "DE",
                                },
                                {
                                    "addressSubNumber": 2,
                                    "isDefaultBilling": True,
                                    "name1": "Buchhaltung",
                                    "street": "Rechnungsweg 2",
                                    "zipCode": "54321",
                                    "city": "Hamburg",
                                    "country": "DE",
                                },
                            ],
                        }
                    }
                }
            },
        )

        OrderCustomerChangeService().apply_result(job)

        self.order.refresh_from_db()
        self.assertEqual(self.order.customer.erp_nr, "20002")
        self.assertEqual(self.order.shipping_address.erp_ans_nr, 1)
        self.assertEqual(self.order.billing_address.erp_ans_nr, 2)
        self.assertEqual(self.order.shipping_address.city, "Berlin")
        self.assertEqual(self.order.billing_address.city, "Hamburg")
        job.refresh_from_db()
        self.assertIn("übernommen", job.next_step)

    def test_apply_result_rejects_an_unknown_customer_number(self):
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_READ,
            operation="requestCustomer",
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            context={"source": CONTEXT_SOURCE, "order_id": self.order.pk, "erp_nr": "20002"},
            result_payload={"customer": None},
        )

        with self.assertRaisesMessage(ValueError, "nicht gefunden"):
            OrderCustomerChangeService().apply_result(job)
