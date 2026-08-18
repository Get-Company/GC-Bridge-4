from types import SimpleNamespace

from django.test import SimpleTestCase

from orders.services.order_sync_workflow import OrderSyncWorkflowService


class ProvisionalCustomerNumberWorkflowTest(SimpleTestCase):
    def test_six_digit_number_from_950000_uses_email_upsert(self):
        self.assertTrue(OrderSyncWorkflowService._is_email_upsert_customer_number("950002"))

    def test_existing_customer_number_does_not_use_email_upsert(self):
        self.assertFalse(OrderSyncWorkflowService._is_email_upsert_customer_number("949999"))

    def test_email_upsert_skips_customer_number_probe(self):
        workflow = SimpleNamespace(state={"email_upsert_customer": True}, step_log=[])

        self.assertEqual(OrderSyncWorkflowService().next_step(workflow), "write_customer")

    def test_email_upsert_uses_the_resolved_microtech_customer_number_afterwards(self):
        workflow = SimpleNamespace(state={"erp_nr": "950002"})

        OrderSyncWorkflowService()._apply_result(
            workflow,
            "write_customer",
            {"customer": {"customerNumber": "100012", "erpAddressNumber": 100012}},
        )

        self.assertEqual(workflow.state["erp_nr"], "100012")
        self.assertEqual(workflow.state["address_number"], 100012)
