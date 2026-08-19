from django.test import TestCase

from microtech.models import (
    RuleTrigger, MicrotechOrderRule, MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleAction, MicrotechDatasetCatalog, MicrotechDatasetField,
)
from microtech.rule_engine.dispatch import resolve_actions, shadow_compare


class _Order:
    firma = "ACME AG"


class DispatchTest(TestCase):
    def _enabled_rule_with_action(self):
        # "order_create" is seeded by migration 0034_seed_triggers; use get_or_create to
        # avoid IntegrityError in the migrated test DB.
        trigger, _ = RuleTrigger.objects.get_or_create(
            code="order_create",
            defaults={
                "label": "Bestellung anlegen",
                "task_name": "orders.microtech_order_upsert",
                "context_root": "orders.Order",
            },
        )
        rule = MicrotechOrderRule.objects.create(
            name="R", trigger=trigger, engine_enabled=True, shadow_mode=False,
            execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE)
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)  # leer = trifft immer
        ds = MicrotechDatasetCatalog.objects.create(
            code="Vorgang", name="Vorgang", source_identifier="Vorgang")
        field = MicrotechDatasetField.objects.create(dataset=ds, field_name="Na1")
        MicrotechOrderRuleAction.objects.create(
            rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset=ds, dataset_field=field, target_value="{{ firma }}")
        return rule

    def test_resolve_actions_renders_template(self):
        self._enabled_rule_with_action()
        actions = resolve_actions(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE, root_instance=_Order())
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].value, "ACME AG")

    def test_shadow_compare_returns_diff_without_applying(self):
        rule = self._enabled_rule_with_action()
        rule.shadow_mode = True
        rule.save(update_fields=["shadow_mode"])
        diff = shadow_compare(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE, root_instance=_Order(),
            legacy_result={"Na1": "Alt"})
        self.assertIn("Na1", diff["changed"])
