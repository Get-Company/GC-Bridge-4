from django.test import TestCase

from microtech.models import (
    RuleTrigger, MicrotechOrderRule, MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup,
)


class MigrationBackfillTest(TestCase):
    def test_helper_backfills_root_group_and_trigger(self):
        from microtech.rule_engine.backfill import backfill_condition_groups
        rule = MicrotechOrderRule.objects.create(
            name="Legacy", condition_logic=MicrotechOrderRule.ConditionLogic.ANY)
        cond = MicrotechOrderRuleCondition.objects.create(
            rule=rule, django_field_path="country_code", operator_code="eq", expected_value="CH")
        RuleTrigger.objects.get_or_create(
            code="order_create", defaults=dict(
                label="Bestellung anlegen",
                task_name="orders.microtech_order_upsert", context_root="orders.Order"))

        backfill_condition_groups(MicrotechOrderRule, MicrotechOrderRuleConditionGroup, RuleTrigger)

        rule.refresh_from_db(); cond.refresh_from_db()
        root = MicrotechOrderRuleConditionGroup.objects.get(rule=rule, parent__isnull=True)
        self.assertEqual(root.logic, MicrotechOrderRule.ConditionLogic.ANY)
        self.assertEqual(cond.group_id, root.id)
        self.assertEqual(rule.trigger.code, "order_create")

    def test_backfill_is_idempotent(self):
        from microtech.rule_engine.backfill import backfill_condition_groups
        rule = MicrotechOrderRule.objects.create(name="R")
        backfill_condition_groups(MicrotechOrderRule, MicrotechOrderRuleConditionGroup, RuleTrigger)
        backfill_condition_groups(MicrotechOrderRule, MicrotechOrderRuleConditionGroup, RuleTrigger)
        self.assertEqual(
            MicrotechOrderRuleConditionGroup.objects.filter(rule=rule, parent__isnull=True).count(), 1)
