from django.test import TestCase

from microtech.models import (
    MicrotechOrderRule, MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleCondition, RuleTrigger,
)
from microtech.rule_engine.editor import serialize_rule_for_edit


class SerializeForEditTest(TestCase):
    def test_serializes_tree_with_ids_and_codes(self):
        trig = RuleTrigger.objects.create(code="ed_o", label="Bestellung",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        rule = MicrotechOrderRule.objects.create(name="R", trigger=trig)
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=root, django_field_path="total",
            operator_code="between", expected_value="5", expected_value_2="9")
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["trigger_id"], trig.id)
        self.assertEqual(data["root_group"]["logic"], "all")
        c = data["root_group"]["conditions"][0]
        self.assertEqual((c["field_path"], c["operator_code"], c["expected_value"], c["expected_value_2"]),
                         ("total", "between", "5", "9"))
