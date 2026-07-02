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


from orders.services.order_sync_workflow import OrderSyncWorkflowService  # noqa: E402


class NextStepResolverTest(TestCase):
    def _wf(self, *, state=None, completed=None):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            state=state or {},
            step_log=[{"step": s, "status": "completed"} for s in (completed or [])],
        )
        return wf

    def test_first_step_is_probe_customer(self):
        wf = self._wf()
        self.assertEqual(OrderSyncWorkflowService().next_step(wf), "probe_customer")

    def test_skips_billing_when_same_as_shipping(self):
        wf = self._wf(
            state={"billing_same_as_shipping": True, "is_new_customer": False},
            completed=["probe_customer", "write_customer", "shipping_address", "shipping_contact"],
        )
        self.assertEqual(OrderSyncWorkflowService().next_step(wf), "set_default_addresses")

    def test_writeback_only_for_new_customer(self):
        wf = self._wf(
            state={"billing_same_as_shipping": True, "is_new_customer": False, "erp_order_id": ""},
            completed=["probe_customer", "write_customer", "shipping_address", "shipping_contact", "set_default_addresses"],
        )
        # Neukunde False -> writeback übersprungen -> nächster ist write_vorgang (kein erp_order_id -> kein probe_vorgang)
        self.assertEqual(OrderSyncWorkflowService().next_step(wf), "write_vorgang")

    def test_all_done_returns_none(self):
        wf = self._wf(
            state={"billing_same_as_shipping": True, "is_new_customer": False, "erp_order_id": ""},
            completed=["probe_customer", "write_customer", "shipping_address", "shipping_contact", "set_default_addresses", "write_vorgang"],
        )
        self.assertIsNone(OrderSyncWorkflowService().next_step(wf))


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
