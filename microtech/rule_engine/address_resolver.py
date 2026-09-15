"""Resolve address output fields (e.g. Na1) from address-write rules.

Evaluates active ``address_write`` rules against a single ``customer.Address``
and returns the ``set_field`` actions of the first matching rule as a
``{dataset_field_name: value}`` map (values rendered through the template layer).
"""
from __future__ import annotations

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template

ADDRESS_WRITE_TASK = "customer.microtech_postal_address"


def resolve_address_fields(address) -> dict[str, str]:
    context = EvaluationContext(address)
    rules = (
        MicrotechOrderRule.objects
        .filter(
            is_active=True,
            engine_enabled=True,
            execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
            trigger__task_name=ADDRESS_WRITE_TASK,
        )
        .prefetch_related(
            "condition_groups",
            "condition_groups__conditions",
            "condition_groups__children",
            "actions",
            "actions__dataset_field",
        )
        .order_by("priority", "id")
    )
    for rule in rules:
        if not rule_matches(rule, context):
            continue
        result: dict[str, str] = {}
        for action in sorted(
            (a for a in rule.actions.all() if a.is_active),
            key=lambda i: (i.priority, i.id),
        ):
            if str(action.action_type) != MicrotechOrderRuleAction.ActionType.SET_FIELD:
                continue
            if not action.dataset_field_id:
                continue
            field_name = str(action.dataset_field.field_name or "")
            if not field_name:
                continue
            result[field_name] = render_template(action.target_value or "", context)
        return result
    return {}


__all__ = ["resolve_address_fields", "ADDRESS_WRITE_TASK"]
