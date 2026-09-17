from django.test import TestCase

from microtech.models import (
    RuleTrigger, MicrotechOrderRule, MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleAction, MicrotechDatasetCatalog, MicrotechDatasetField,
    RuleEngineExecutionLog,
)
from microtech.rule_engine.dispatch import resolve_actions, shadow_compare
from microtech.rule_engine.execution import RuleExecutionService


class _Order:
    firma = "ACME AG"


class DispatchTest(TestCase):
    def _enabled_rule_with_action(self, *, priority=100, field_name="Na1", target_value="{{ firma }}"):
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
            name=f"R {priority}", priority=priority, trigger=trigger,
            engine_enabled=True, shadow_mode=False,
            execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE)
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)  # leer = trifft immer
        ds = MicrotechDatasetCatalog.objects.create(
            code=f"Vorgang-{priority}", name="Vorgang", source_identifier="Vorgang")
        field = MicrotechDatasetField.objects.create(dataset=ds, field_name=field_name)
        MicrotechOrderRuleAction.objects.create(
            rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset=ds, dataset_field=field, target_value=target_value)
        return rule

    def test_resolve_actions_renders_template(self):
        self._enabled_rule_with_action()
        actions = resolve_actions(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE, root_instance=_Order())
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].value, "ACME AG")

    def test_resolve_actions_runs_every_matching_rule_in_priority_order(self):
        self._enabled_rule_with_action(priority=10, field_name="Na1")
        self._enabled_rule_with_action(priority=20, field_name="Na2", target_value="Zusatz")

        actions = resolve_actions(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
            root_instance=_Order(),
        )

        self.assertEqual([(action.field_path, action.value) for action in actions], [
            ("Na1", "ACME AG"),
            ("Na2", "Zusatz"),
        ])

    def test_shadow_compare_returns_diff_without_applying(self):
        rule = self._enabled_rule_with_action()
        rule.shadow_mode = True
        rule.save(update_fields=["shadow_mode"])
        diff = shadow_compare(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE, root_instance=_Order(),
            legacy_result={"Na1": "Alt"})
        self.assertIn("Na1", diff["changed"])

    def test_audit_log_records_applied_and_skipped_rules(self):
        applied = self._enabled_rule_with_action(priority=10)
        disabled = self._enabled_rule_with_action(priority=20)
        disabled.engine_enabled = False
        disabled.save(update_fields=("engine_enabled",))
        inactive = self._enabled_rule_with_action(priority=30)
        inactive.is_active = False
        inactive.save(update_fields=("is_active",))

        matches = RuleExecutionService().resolve_matching_rules(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
            root_instance=_Order(),
            audit_mode="live",
            audit_subject="Bestellung TEST-1",
        )

        self.assertEqual([match.rule.id for match in matches], [applied.id])
        logs = {entry.rule_id: entry for entry in RuleEngineExecutionLog.objects.all()}
        self.assertEqual(logs[applied.id].outcome, RuleEngineExecutionLog.Outcome.APPLIED)
        self.assertIn('"target": "Na1"', logs[applied.id].actions_json)
        self.assertEqual(logs[disabled.id].outcome, RuleEngineExecutionLog.Outcome.SKIPPED_ENGINE_DISABLED)
        self.assertEqual(logs[inactive.id].outcome, RuleEngineExecutionLog.Outcome.SKIPPED_INACTIVE)
