from types import SimpleNamespace

from django.test import SimpleTestCase

from orders.services.order_sync_workflow import OrderSyncWorkflowService


class ProvisionalCustomerNumberWorkflowTest(SimpleTestCase):
    def test_six_digit_number_from_950000_uses_new_customer_number_allocation(self):
        self.assertTrue(OrderSyncWorkflowService._is_provisional_customer_number("950002"))

    def test_existing_customer_number_does_not_use_new_customer_number_allocation(self):
        self.assertFalse(OrderSyncWorkflowService._is_provisional_customer_number("949999"))

    def test_new_customer_sequence_writes_back_before_order_creation(self):
        workflow = SimpleNamespace(state={"is_new_customer": True}, step_log=[{"step": "write_customer", "status": "completed"}])

        self.assertEqual(OrderSyncWorkflowService().next_step(workflow), "writeback_adrnr")

    def test_provisional_customer_upsert_uses_the_allocated_microtech_customer_number_afterwards(self):
        workflow = SimpleNamespace(state={"erp_nr": "950002", "requested_customer_number": "950002"})

        OrderSyncWorkflowService()._apply_result(
            workflow,
            "write_customer",
            {"customer": {"customerNumber": "100012", "erpAddressNumber": 100012}},
        )

        self.assertEqual(workflow.state["erp_nr"], "100012")
        self.assertEqual(workflow.state["address_number"], 100012)

    def test_provisional_customer_upsert_rejects_an_unresolved_shopware_placeholder(self):
        workflow = SimpleNamespace(state={"erp_nr": "950002", "requested_customer_number": "950002"})

        with self.assertRaisesRegex(ValueError, "vorläufige Shopware-Kundennummer"):
            OrderSyncWorkflowService()._apply_result(
                workflow,
                "write_customer",
                {"customer": {"customerNumber": "950002", "erpAddressNumber": 950002}},
            )
