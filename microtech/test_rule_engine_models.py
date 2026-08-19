from django.test import TestCase

from microtech.models import RuleTrigger


class RuleTriggerModelTest(TestCase):
    def test_for_task_returns_active_triggers_for_task_name(self):
        RuleTrigger.objects.create(
            code="test_trigger_active", label="Aktiv",
            task_name="test.dummy_task", context_root="orders.Order",
        )
        RuleTrigger.objects.create(
            code="test_trigger_inactive", label="Aus", task_name="test.dummy_task",
            context_root="orders.Order", is_active=False,
        )
        result = list(RuleTrigger.for_task("test.dummy_task"))
        self.assertEqual([t.code for t in result], ["test_trigger_active"])


class OrderRuleEngineFieldsTest(TestCase):
    def test_new_engine_fields_have_safe_defaults(self):
        from microtech.models import MicrotechOrderRule
        rule = MicrotechOrderRule.objects.create(name="R")
        self.assertEqual(rule.execution_phase, MicrotechOrderRule.ExecutionPhase.BEFORE)
        self.assertTrue(rule.shadow_mode)          # Einführung: Schatten an
        self.assertFalse(rule.engine_enabled)      # Einführung: neue Engine aus
        self.assertIsNone(rule.trigger)


class ConditionGroupModelTest(TestCase):
    def test_nested_groups_and_second_value(self):
        from microtech.models import (
            MicrotechOrderRule, MicrotechOrderRuleConditionGroup, MicrotechOrderRuleCondition,
        )
        rule = MicrotechOrderRule.objects.create(name="R")
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        sub = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, parent=root, logic=MicrotechOrderRule.ConditionLogic.ANY,
        )
        cond = MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="total",
            operator_code="between", expected_value="500", expected_value_2="9999",
        )
        self.assertEqual(list(root.children.all()), [sub])
        self.assertEqual(cond.group, sub)
        self.assertEqual(cond.expected_value_2, "9999")


class RuleConstantTest(TestCase):
    def test_seeded_eu_countries_and_it_group(self):
        from microtech.models import RuleConstant
        eu = RuleConstant.get_list("eu_country_codes")
        self.assertIn("DE", eu)
        self.assertIn("IT", eu)
        self.assertTrue(RuleConstant.get_scalar("italian_b2b_group"))
