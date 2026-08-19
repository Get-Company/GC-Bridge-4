from django.test import TestCase
from microtech.models import (
    MicrotechOrderRule, MicrotechOrderRuleConditionGroup, MicrotechOrderRuleCondition,
    MicrotechOrderRuleDjangoField,
)
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches


class _Order:
    country_code = "CH"
    customer_group = "Haendler"
    total = 750


class EvaluationTest(TestCase):
    def setUp(self):
        for path, kind in [("country_code", "string"), ("customer_group", "string"), ("total", "decimal")]:
            MicrotechOrderRuleDjangoField.objects.create(
                field_path=path, label=path, value_kind=kind)

    def _rule_with_tree(self):
        rule = MicrotechOrderRule.objects.create(name="R")
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        sub = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, parent=root, logic=MicrotechOrderRule.ConditionLogic.ANY)
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=root, django_field_path="country_code",
            operator_code="eq", expected_value="CH")
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="customer_group",
            operator_code="eq", expected_value="Haendler")
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="total",
            operator_code="between", expected_value="500", expected_value_2="9999")
        return rule

    def test_nested_and_or_matches(self):
        rule = self._rule_with_tree()
        self.assertTrue(rule_matches(rule, EvaluationContext(_Order())))

    def test_empty_root_is_global_fallback(self):
        rule = MicrotechOrderRule.objects.create(name="Empty")
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        self.assertTrue(rule_matches(rule, EvaluationContext(_Order())))
