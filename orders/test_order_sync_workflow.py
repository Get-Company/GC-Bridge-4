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


from unittest.mock import MagicMock, patch  # noqa: E402

from microtech.models import MicrotechGraphQLJob  # noqa: E402


class AdvanceHandlerTest(TestCase):
    def _job(self, workflow, step, result):
        return MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="op",
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            context={"workflow_id": workflow.id, "step": step},
            result_payload=result,
            continuation="microtech_order_sync_advance",
        )

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_advance_probe_customer_found_marks_existing(self, mock_submit):
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=make_order(), status=MicrotechOrderSyncWorkflow.Status.WAITING, current_step="probe_customer"
        )
        job = self._job(wf, "probe_customer", {"customer": {"customerNumber": "100012", "erpAddressNumber": 100012}})

        OrderSyncWorkflowService().advance(job)

        wf.refresh_from_db()
        self.assertFalse(wf.state["is_new_customer"])
        self.assertEqual(wf.state["address_number"], 100012)
        self.assertIn({"step": "probe_customer", "status": "completed"}, [
            {"step": e["step"], "status": e["status"]} for e in wf.step_log
        ])
        mock_submit.assert_called_once()  # nächster Step (write_customer) submitted

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_advance_ignores_stale_step(self, mock_submit):
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=make_order(), status=MicrotechOrderSyncWorkflow.Status.WAITING, current_step="write_customer"
        )
        job = self._job(wf, "probe_customer", {"customer": None})

        OrderSyncWorkflowService().advance(job)

        mock_submit.assert_not_called()


class StartAndSubmitTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_start_creates_workflow_and_submits_probe(self, mock_submit, mock_client):
        job = MagicMock(pk=1)
        mock_submit.return_value = job
        order = make_order()

        wf = OrderSyncWorkflowService().start_for_order(order)

        wf.refresh_from_db()
        self.assertEqual(wf.current_step, "probe_customer")
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.WAITING)
        self.assertEqual(wf.state["erp_nr"], order.customer.erp_nr)
        called = mock_submit.call_args.kwargs
        self.assertEqual(called["kind"], MicrotechGraphQLJob.Kind.CUSTOMER_READ)
        self.assertEqual(called["context"]["step"], "probe_customer")
        self.assertEqual(called["continuation"], "microtech_order_sync_advance")

    def test_start_rejects_second_active_workflow(self):
        order = make_order()
        MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING)
        with self.assertRaises(ValueError):
            OrderSyncWorkflowService().start_for_order(order)


class LocalStepTest(TestCase):
    @patch("customer.services.customer_upsert_microtech.CustomerUpsertMicrotechService._sync_new_customer_number_to_shopware")
    def test_writeback_adrnr_calls_shopware_sync(self, mock_sync):
        mock_sync.return_value = True
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            state={"erp_nr": order.customer.erp_nr, "is_new_customer": True},
        )

        OrderSyncWorkflowService()._run_local_step(wf, "writeback_adrnr")

        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.kwargs["erp_nr"], order.customer.erp_nr)


class OrderStepTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_write_vorgang_creates_when_no_beleg(self, mock_submit, mock_client_cls):
        mock_submit.return_value = MagicMock(pk=5)
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            state={"erp_nr": order.customer.erp_nr, "beleg_nr": ""},
        )

        with patch(
            "orders.services.order_upsert_microtech.OrderUpsertMicrotechService._build_graphql_positions",
            return_value=([], MagicMock()),
        ):
            OrderSyncWorkflowService()._submit_order_step(wf, "write_vorgang")

        called = mock_submit.call_args.kwargs
        self.assertEqual(called["kind"], MicrotechGraphQLJob.Kind.ORDER_UPSERT)
        self.assertEqual(called["operation"], "createVorgang")


class ReconcileTest(TestCase):
    def _waiting_wf(self, step, job_status, error=""):
        order = make_order()
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="op",
            status=job_status,
            error_message=error,
            context={"step": step},
            external_job_id=f"ext-{step}-{job_status}",
        )
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step=step,
            current_job=job,
            state={"erp_nr": order.customer.erp_nr},
        )
        return wf

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_failed_write_step_marks_workflow_failed(self, mock_submit):
        wf = self._waiting_wf("write_customer", MicrotechGraphQLJob.Status.FAILED, error="boom")
        changed = OrderSyncWorkflowService().reconcile_failures()
        wf.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.FAILED)
        self.assertIn("boom", wf.error_message)

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_failed_probe_customer_treated_as_new(self, mock_submit):
        wf = self._waiting_wf("probe_customer", MicrotechGraphQLJob.Status.FAILED, error="not found")
        OrderSyncWorkflowService().reconcile_failures()
        wf.refresh_from_db()
        self.assertTrue(wf.state["is_new_customer"])
        mock_submit.assert_called_once()


class ResumeTest(TestCase):
    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_resume_resubmits_current_step(self, mock_submit):
        mock_submit.return_value = MagicMock(pk=9)
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.FAILED,
            current_step="shipping_address",
            error_message="boom",
            state={"erp_nr": order.customer.erp_nr},
        )

        OrderSyncWorkflowService().resume(wf)

        wf.refresh_from_db()
        self.assertEqual(wf.error_message, "")
        mock_submit.assert_called_once_with(wf, "shipping_address")

    def test_resume_noop_when_not_failed(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING)
        self.assertIsNone(OrderSyncWorkflowService().resume(wf))
