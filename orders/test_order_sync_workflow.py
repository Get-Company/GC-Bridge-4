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
from microtech.services.job_sentinel import MicrotechJobSentinelService  # noqa: E402
from orders.services.order_sync import OrderSyncService  # noqa: E402


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

    def test_apply_address_result_falls_back_to_persisted_address_sub_number(self):
        order = make_order()
        order.shipping_address.erp_ans_nr = 7
        order.shipping_address.save(update_fields=("erp_ans_nr",))
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="shipping_address",
            state={"billing_same_as_shipping": True},
        )

        OrderSyncWorkflowService()._apply_result(wf, "shipping_address", {})

        self.assertEqual(wf.state["shipping_ans_nr"], 7)
        self.assertEqual(wf.state["billing_ans_nr"], 7)

    def test_apply_address_result_reads_customer_addresses(self):
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=make_order(),
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="shipping_address",
            state={"billing_same_as_shipping": False},
        )
        result = {
            "customer": {
                "addresses": [
                    {"addressSubNumber": 4, "isDefaultShipping": False},
                    {"addressSubNumber": 8, "isDefaultShipping": True},
                ]
            }
        }

        OrderSyncWorkflowService()._apply_result(wf, "shipping_address", result)

        self.assertEqual(wf.state["shipping_ans_nr"], 8)

    def test_apply_created_address_without_sub_number_defaults_to_first_sub_number(self):
        order = make_order()
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="createPostalAddress",
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
        )
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="shipping_address",
            state={"address_number": int(order.customer.erp_nr), "billing_same_as_shipping": True},
            current_job=job,
        )

        OrderSyncWorkflowService()._apply_result(wf, "shipping_address", {}, job=job)

        order.shipping_address.refresh_from_db()
        self.assertEqual(wf.state["shipping_ans_nr"], 1)
        self.assertEqual(wf.state["billing_ans_nr"], 1)
        self.assertEqual(order.shipping_address.erp_ans_nr, 1)

    def test_apply_address_result_persists_address_identity(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="shipping_address",
            state={"address_number": int(order.customer.erp_nr), "billing_same_as_shipping": False},
        )

        OrderSyncWorkflowService()._apply_result(
            wf,
            "shipping_address",
            {"postalAddress": {"addressNumber": int(order.customer.erp_nr), "addressSubNumber": 12}},
        )

        order.shipping_address.refresh_from_db()
        self.assertEqual(order.shipping_address.erp_nr, int(order.customer.erp_nr))
        self.assertEqual(order.shipping_address.erp_ans_nr, 12)

    def test_apply_contact_result_persists_contact_identity(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="shipping_contact",
            state={"address_number": int(order.customer.erp_nr), "shipping_ans_nr": 12},
        )

        OrderSyncWorkflowService()._apply_result(
            wf,
            "shipping_contact",
            {
                "contactPerson": {
                    "addressNumber": int(order.customer.erp_nr),
                    "addressSubNumber": 12,
                    "contactNumber": 3,
                }
            },
        )

        order.shipping_address.refresh_from_db()
        self.assertEqual(order.shipping_address.erp_ans_nr, 12)
        self.assertEqual(order.shipping_address.erp_asp_nr, 3)
        self.assertEqual(order.shipping_address.erp_asp_id, 3)

    def test_apply_contact_result_reads_nested_customer_contacts(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="shipping_contact",
            state={"address_number": int(order.customer.erp_nr), "shipping_ans_nr": 8},
        )
        result = {
            "customer": {
                "addresses": [
                    {"addressSubNumber": 4, "contacts": [{"contactNumber": 1, "isDefault": True}]},
                    {"addressSubNumber": 8, "contacts": [{"contactNumber": 5, "isDefault": True}]},
                ]
            }
        }

        OrderSyncWorkflowService()._apply_result(wf, "shipping_contact", result)

        order.shipping_address.refresh_from_db()
        self.assertEqual(order.shipping_address.erp_asp_nr, 5)


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


class ShopwareAddressMatchingTest(TestCase):
    def test_upsert_address_matches_same_location_and_contact_before_role_fallback(self):
        order = make_order()
        existing = Address.objects.create(
            customer=order.customer,
            street="Hauptstr. 1",
            postal_code="34117",
            city="Kassel",
            first_name="Anna",
            last_name="Alt",
            is_shipping=True,
            erp_ans_nr=12,
            erp_asp_nr=3,
        )
        matching_contact = Address.objects.create(
            customer=order.customer,
            street="Hauptstr. 1",
            postal_code="34117",
            city="Kassel",
            first_name="Berta",
            last_name="Neu",
            erp_ans_nr=12,
            erp_asp_nr=4,
        )

        address = OrderSyncService()._upsert_address(
            customer=order.customer,
            address_data={
                "street": "Hauptstr. 1",
                "zipcode": "34117",
                "city": "Kassel",
                "firstName": "Berta",
                "lastName": "Neu",
            },
            fallback_email="",
            is_invoice=False,
            is_shipping=True,
        )

        existing.refresh_from_db()
        matching_contact.refresh_from_db()
        self.assertEqual(address.pk, matching_contact.pk)
        self.assertEqual(existing.first_name, "Anna")
        self.assertTrue(matching_contact.is_shipping)


class ContactStepTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_address_step_reuses_matching_anschrift_for_different_contact_address(
        self,
        mock_submit,
        mock_client_cls,
    ):
        mock_submit.return_value = MagicMock(pk=8)
        order = make_order()
        sibling = Address.objects.create(
            customer=order.customer,
            street="Hauptstr. 1",
            postal_code="34117",
            city="Kassel",
            country_code="DE",
            erp_nr=int(order.customer.erp_nr),
            erp_ans_nr=12,
            erp_asp_nr=3,
            first_name="Anna",
            last_name="Alt",
        )
        order.shipping_address.street = sibling.street
        order.shipping_address.postal_code = sibling.postal_code
        order.shipping_address.city = sibling.city
        order.shipping_address.country_code = sibling.country_code
        order.shipping_address.first_name = "Berta"
        order.shipping_address.last_name = "Neu"
        order.shipping_address.save()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.RUNNING,
            state={"erp_nr": order.customer.erp_nr, "address_number": int(order.customer.erp_nr)},
        )

        OrderSyncWorkflowService().submit_step(wf, "shipping_address")

        order.shipping_address.refresh_from_db()
        called = mock_submit.call_args.kwargs
        self.assertEqual(called["operation"], "updatePostalAddress")
        self.assertEqual(called["request_payload"]["addressSubNumber"], 12)
        self.assertEqual(order.shipping_address.erp_ans_nr, 12)
        self.assertIsNone(order.shipping_address.erp_asp_nr)

    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_shipping_contact_falls_back_to_locally_persisted_ans_nr(self, mock_submit, mock_client_cls):
        mock_submit.return_value = MagicMock(pk=6)
        order = make_order()
        order.shipping_address.erp_ans_nr = 7
        order.shipping_address.save(update_fields=("erp_ans_nr",))
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.RUNNING,
            state={"erp_nr": order.customer.erp_nr, "address_number": int(order.customer.erp_nr)},
        )

        OrderSyncWorkflowService().submit_step(wf, "shipping_contact")

        called = mock_submit.call_args.kwargs
        self.assertEqual(called["operation"], "createContactPerson")
        self.assertEqual(called["request_payload"]["addressSubNumber"], 7)

    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_shipping_contact_recovers_sub_number_from_previous_create_address_job(self, mock_submit, mock_client_cls):
        mock_submit.return_value = MagicMock(pk=7)
        order = make_order()
        previous_job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="createPostalAddress",
            status=MicrotechGraphQLJob.Status.FAILED,
            result_payload={},
        )
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.FAILED,
            current_step="shipping_contact",
            current_job=previous_job,
            state={"erp_nr": order.customer.erp_nr, "address_number": int(order.customer.erp_nr)},
        )

        OrderSyncWorkflowService().submit_step(wf, "shipping_contact")

        order.shipping_address.refresh_from_db()
        called = mock_submit.call_args.kwargs
        self.assertEqual(called["request_payload"]["addressSubNumber"], 1)
        self.assertEqual(order.shipping_address.erp_ans_nr, 1)


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

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_failed_probe_customer_technical_error_marks_workflow_failed(self, mock_submit):
        wf = self._waiting_wf("probe_customer", MicrotechGraphQLJob.Status.FAILED, error="COM unavailable")
        OrderSyncWorkflowService().reconcile_failures()
        wf.refresh_from_db()
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.FAILED)
        mock_submit.assert_not_called()

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_technical_probe_error_logs_warning(self, mock_submit):
        self._waiting_wf("probe_customer", MicrotechGraphQLJob.Status.FAILED, error="COM unavailable")
        with self.assertLogs("orders.services.order_sync_workflow", level="WARNING") as logs:
            OrderSyncWorkflowService().reconcile_failures()
        self.assertTrue(any("COM unavailable" in message for message in logs.output))


class JobDeletionCleanupTest(TestCase):
    def test_deleting_current_job_removes_waiting_order_workflow_reference(self):
        order = make_order()
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.ORDER_UPSERT,
            operation="createVorgang",
            status=MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
            external_job_id="ext-order-cleanup",
        )
        MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step="write_vorgang",
            current_job=job,
        )

        MicrotechJobSentinelService().delete_job(job_id=job.pk, delete_remote=False)

        self.assertFalse(MicrotechGraphQLJob.objects.filter(pk=job.pk).exists())
        self.assertFalse(MicrotechOrderSyncWorkflow.objects.filter(order=order).exists())


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

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_resume_skips_already_completed_step(self, mock_submit):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.FAILED,
            current_step="probe_customer",
            error_message="submit des Folgeschritts fehlgeschlagen",
            state={"erp_nr": order.customer.erp_nr, "is_new_customer": False},
            step_log=[{"step": "probe_customer", "status": "completed"}],
        )

        OrderSyncWorkflowService().resume(wf)

        # probe_customer ist bereits erledigt -> nicht erneut submitten, sondern den Folgeschritt
        mock_submit.assert_called_once()
        self.assertEqual(mock_submit.call_args.args[1], "write_customer")


class SubmitFailureTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_start_marks_workflow_failed_when_submit_raises(self, mock_submit, mock_client):
        mock_submit.side_effect = RuntimeError("wrapper down")
        order = make_order()

        with self.assertRaises(RuntimeError):
            OrderSyncWorkflowService().start_for_order(order)

        wf = MicrotechOrderSyncWorkflow.objects.get(order=order)
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.FAILED)
        self.assertIn("wrapper down", wf.error_message)
        self.assertEqual(wf.current_step, "probe_customer")
        self.assertEqual(wf.step_log[-1]["step"], "probe_customer")
        self.assertEqual(wf.step_log[-1]["status"], "failed")

    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_failed_start_can_be_resumed(self, mock_submit, mock_client):
        mock_submit.side_effect = RuntimeError("wrapper down")
        order = make_order()
        with self.assertRaises(RuntimeError):
            OrderSyncWorkflowService().start_for_order(order)
        wf = MicrotechOrderSyncWorkflow.objects.get(order=order)

        mock_submit.side_effect = None
        mock_submit.return_value = MagicMock(pk=2)
        OrderSyncWorkflowService().resume(wf)

        wf.refresh_from_db()
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.WAITING)
        self.assertEqual(wf.current_step, "probe_customer")


class LogStepDedupeTest(TestCase):
    def test_log_step_does_not_duplicate_completed_entries(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(order=order)
        service = OrderSyncWorkflowService()

        service._log_step(wf, "probe_customer", "completed")
        service._log_step(wf, "probe_customer", "completed")

        entries = [e for e in wf.step_log if e["step"] == "probe_customer" and e["status"] == "completed"]
        self.assertEqual(len(entries), 1)

    def test_log_step_allows_repeated_failed_entries(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(order=order)
        service = OrderSyncWorkflowService()

        service._log_step(wf, "write_customer", "failed", error="a")
        service._log_step(wf, "write_customer", "failed", error="b")

        entries = [e for e in wf.step_log if e["step"] == "write_customer" and e["status"] == "failed"]
        self.assertEqual(len(entries), 2)


class SetDefaultAddressesTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_falls_back_to_locally_persisted_ans_nr(self, mock_submit, mock_client):
        mock_submit.return_value = MagicMock(pk=3)
        order = make_order()
        order.shipping_address.erp_ans_nr = "3"
        order.shipping_address.save(update_fields=("erp_ans_nr",))
        order.billing_address.erp_ans_nr = "4"
        order.billing_address.save(update_fields=("erp_ans_nr",))
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.RUNNING,
            state={"erp_nr": order.customer.erp_nr, "billing_same_as_shipping": False},
        )

        OrderSyncWorkflowService().submit_step(wf, "set_default_addresses")

        input_data = mock_submit.call_args.kwargs["request_payload"]["input"]
        self.assertEqual(input_data["defaultShippingAddressNumber"], 3)
        self.assertEqual(input_data["defaultBillingAddressNumber"], 4)

    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_rejects_missing_ans_nr(self, mock_submit, mock_client):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.RUNNING,
            state={"erp_nr": order.customer.erp_nr, "billing_same_as_shipping": True},
        )

        with self.assertRaises(ValueError):
            OrderSyncWorkflowService().submit_step(wf, "set_default_addresses")
        mock_submit.assert_not_called()
