from django.test import TestCase

from microtech.models import RuleTrigger


class RuleTriggerModelTest(TestCase):
    def test_for_task_returns_active_triggers_for_task_name(self):
        RuleTrigger.objects.create(
            code="order_create", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order",
        )
        RuleTrigger.objects.create(
            code="inactive", label="Aus", task_name="orders.microtech_order_upsert",
            context_root="orders.Order", is_active=False,
        )
        result = list(RuleTrigger.for_task("orders.microtech_order_upsert"))
        self.assertEqual([t.code for t in result], ["order_create"])
