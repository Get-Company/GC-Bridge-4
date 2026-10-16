import json
from copy import deepcopy
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase, TestCase

from orders.admin import OrderAdmin
from orders.models import MicrotechOrderSyncWorkflow, Order
from orders.services.order_price import OrderPriceService
from orders.services.order_sync_workflow import OrderSyncWorkflowService
from orders.test_order_sync_workflow import make_order
from microtech.models import MicrotechGraphQLJob


class ConvertedInvoicePriceTest(SimpleTestCase):
    def setUp(self):
        self.expected = {
            "gross": True, "currency": "EUR", "netto": "66.03", "brutto": "78.57",
            "positions": [{"erpNumber": "204113", "quantity": "50",
                           "unitPrice": "0.6557", "totalPrice": "32.79"}],
        }
        self.result = {"vorgang": {
            "belegNr": "TEST/1", "currency": "EUR", "netto": "66.0214", "brutto": "78.5655",
            "positions": [{"erpNumber": "204113", "quantity": "50.0", "unit": "Einheit",
                           "unitPrice": "55.1008", "totalPrice": "27.5504",
                           "grossUnitPrice": "65.57", "grossTotalPrice": "32.785"}],
        }}

    def test_generic_invoice_unit_with_proven_per_hundred_basis_passes(self):
        self.assertEqual(OrderPriceService().verify_export(self.expected, self.result)["positions_checked"], 1)

    def test_net_invoice_uses_its_own_per_hundred_basis(self):
        self.expected["gross"] = False
        self.expected["positions"][0].update(unitPrice="0.551008", totalPrice="27.55")
        OrderPriceService().verify_export(self.expected, self.result)

    def test_generic_label_does_not_hide_wrong_unit_or_line_prices(self):
        for changes in ({"grossUnitPrice": "66.57"}, {"grossTotalPrice": "3278.50"},
                        {"grossUnitPrice": "6557.00"}, {"grossTotalPrice": None}):
            with self.subTest(changes=changes):
                result = deepcopy(self.result)
                result["vorgang"]["positions"][0].update(changes)
                with self.assertRaisesRegex(ValueError, "Preisabweichung"):
                    OrderPriceService().verify_export(self.expected, result)

    def test_explicit_piece_unit_is_not_silently_reinterpreted(self):
        self.result["vorgang"]["positions"][0]["unit"] = "Stück"
        with self.assertRaisesRegex(ValueError, "Preisabweichung"):
            OrderPriceService().verify_export(self.expected, self.result)


class WorkflowStatusDescriptionTest(SimpleTestCase):
    def workflow(self, **overrides):
        data = dict(status="failed", current_step="verify_vorgang_prices",
                    state={"beleg_nr": "TEST/1"}, error_message="Versandpreis weicht ab.",
                    step_log=[{"step": "write_vorgang", "status": "completed"}])
        return MicrotechOrderSyncWorkflow(**(data | overrides))

    def test_failed_check_does_not_claim_document_creation_failed(self):
        self.assertEqual(self.workflow().status_summary, "Angelegt · Preisprüfung fehlgeschlagen")
        self.assertEqual(self.workflow(step_log=[]).status_summary,
                         "Beleg vorhanden · Preisprüfung fehlgeschlagen")
        self.assertEqual(self.workflow(current_step="write_vorgang").status_summary, "Fehlgeschlagen")

    def test_detail_includes_the_workflow_error_even_when_remote_read_succeeded(self):
        order = MagicMock(spec=Order)
        order.microtech_sync_workflows.order_by.return_value.first.return_value = self.workflow()
        rendered = str(OrderAdmin.microtech_sync_status_for_order(order))
        self.assertIn("Angelegt", rendered)
        self.assertIn("Versandpreis weicht ab.", rendered)

    def test_polling_api_uses_the_same_description(self):
        order = Order(pk=1, order_number="TEST", erp_order_id="TEST/1")
        workflow = self.workflow(pk=2)
        model_admin = OrderAdmin(Order, admin.site)
        with patch.object(model_admin, "get_object", return_value=order), \
                patch.object(model_admin, "has_view_permission", return_value=True), \
                patch.object(type(order.microtech_sync_workflows), "select_related") as query:
            query.return_value.order_by.return_value.first.return_value = workflow
            response = model_admin.microtech_sync_status_view(RequestFactory().get("/"), "1")
        payload = json.loads(response.content)
        self.assertEqual(payload["status_display"], workflow.status_summary)
        self.assertEqual(payload["error_message"], workflow.error_message)


class CorrectedAddressMappingTest(TestCase):
    def setUp(self):
        self.order = make_order()
        self.shipping = self.order.shipping_address
        self.billing = self.order.billing_address
        self.shipping.erp_ans_nr, self.shipping.erp_asp_nr = 1, 2
        self.billing.erp_ans_nr, self.billing.erp_asp_nr = 2, 2
        self.shipping.save()
        self.billing.save()
        self.workflow = MicrotechOrderSyncWorkflow.objects.create(
            order=self.order, current_step="shipping_contact",
            state={"shipping_ans_nr": 2, "billing_ans_nr": 2},
        )

    def test_legacy_contact_result_cannot_restore_a_corrected_postal_mapping(self):
        with self.assertRaisesRegex(ValueError, "nicht überschrieben"):
            OrderSyncWorkflowService()._apply_result(self.workflow, "shipping_contact", {
                "contactPerson": {"addressSubNumber": 2, "contactNumber": 2},
            })
        self.shipping.refresh_from_db()
        self.assertEqual(self.shipping.erp_ans_nr, 1)

    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    def test_resume_stops_before_any_remote_write_for_an_old_mapping(self, client):
        with self.assertRaisesRegex(ValueError, "nicht überschrieben"):
            OrderSyncWorkflowService().submit_step(self.workflow, "shipping_contact")
        client.assert_not_called()

    def test_job_snapshot_protects_contact_only_corrections_too(self):
        self.workflow.state["shipping_ans_nr"] = 1
        service = OrderSyncWorkflowService()
        mappings = service._address_mappings(self.workflow)
        mappings["shipping"]["asp_nr"] = 1
        job = MicrotechGraphQLJob(context={"address_mappings": mappings})
        with self.assertRaisesRegex(ValueError, "zwischenzeitlich|seit dem Start"):
            service._apply_result(self.workflow, "shipping_contact", {
                "contactPerson": {"addressSubNumber": 1, "contactNumber": 1},
            }, job=job)
        self.shipping.refresh_from_db()
        self.assertEqual(self.shipping.erp_asp_nr, 2)

    def test_different_recipients_cannot_share_the_identical_postal_contact_pair(self):
        self.shipping.erp_ans_nr = 2
        self.shipping.first_name = "Edith"
        self.shipping.name1 = "Frau"
        self.billing.first_name = "Enno"
        self.billing.name1 = "Firma"
        self.workflow.state = {}
        with self.assertRaisesRegex(ValueError, "dieselbe Microtech-Anschrift"):
            OrderSyncWorkflowService()._assert_address_mappings_current(self.workflow)

    def test_different_contacts_may_still_share_one_postal_address(self):
        self.shipping.erp_ans_nr = 2
        self.shipping.erp_asp_nr = 1
        self.shipping.first_name = "Edith"
        self.workflow.state = {}
        OrderSyncWorkflowService()._assert_address_mappings_current(self.workflow)
