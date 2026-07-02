from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from customer.models import Address, Customer
from orders.models import MicrotechOrderSyncWorkflow, Order

_ORDER_SEQ = [0]


def make_order() -> Order:
    """Erzeugt eine minimale, gültige Order-Instanz für Tests."""
    _ORDER_SEQ[0] += 1
    n = _ORDER_SEQ[0]
    api_id = f"WF{n}"
    customer = Customer.objects.create(erp_nr=f"100{n:05d}", name="Testkunde GmbH", is_gross=True)
    billing = Address.objects.create(customer=customer, first_name="Max", last_name="Mustermann", country_code="DE", is_invoice=True)
    shipping = Address.objects.create(customer=customer, first_name="Max", last_name="Mustermann", country_code="DE", is_shipping=True)
    return Order.objects.create(
        api_id=api_id,
        order_number=f"ORDER-{api_id}",
        customer=customer,
        billing_address=billing,
        shipping_address=shipping,
        payment_method="Rechnung",
        shipping_method="Standard",
        total_price=Decimal("0.00"),
        total_tax=Decimal("0.00"),
        shipping_costs=Decimal("0.00"),
    )


class WorkflowModelTest(TestCase):
    def test_defaults(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(order=order)
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.PENDING)
        self.assertEqual(wf.state, {})
        self.assertEqual(wf.step_log, [])
        self.assertTrue(wf.is_active)

    def test_only_one_active_workflow_per_order(self):
        order = make_order()
        MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING)
        with self.assertRaises(IntegrityError):
            MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.PENDING)
