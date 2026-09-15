"""Build the ``ResolvedOrderRule`` contract from the new rule engine.

Reproduces the *lived* semantics of the legacy ``OrderRuleResolverService``
(first matching active rule -> its dataset actions, plus customer type from the
address heuristic) but selects rules through the new trigger/condition-group
model and renders action values through the template layer. The return type is
the same ``ResolvedOrderRule`` the Microtech upsert already consumes, so no
downstream change is required.
"""
from __future__ import annotations

from dataclasses import replace

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template
from orders.services.order_rule_resolver import (
    ResolvedDatasetAction,
    ResolvedOrderRule,
    detect_customer_type as _detect_customer_type,
)

ORDER_CREATE_TASK = "orders.microtech_order_upsert"


def detect_customer_type(order) -> str:
    return _detect_customer_type(order=order)


def _dataset_action(action, context) -> ResolvedDatasetAction:
    action_type = str(action.action_type or "")
    value = render_template(action.target_value or "", context)
    if action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.dataset_field_id:
        field = action.dataset_field
        dataset = field.dataset
        return ResolvedDatasetAction(
            action_type=action_type,
            dataset_source_identifier=str(getattr(dataset, "source_identifier", "") or ""),
            dataset_name=str(getattr(dataset, "name", "") or ""),
            dataset_field_name=str(field.field_name or ""),
            dataset_field_type=str(field.field_type or ""),
            target_value=value,
        )
    return ResolvedDatasetAction(action_type=action_type, target_value=value)


def resolve_order_rule(order) -> ResolvedOrderRule:
    context = EvaluationContext(order)
    rules = (
        MicrotechOrderRule.objects
        .filter(
            is_active=True,
            engine_enabled=True,
            execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
            trigger__task_name=ORDER_CREATE_TASK,
        )
        .prefetch_related(
            "condition_groups",
            "condition_groups__conditions",
            "condition_groups__children",
            "actions",
            "actions__dataset",
            "actions__dataset_field",
        )
        .order_by("priority", "id")
    )
    customer_type = detect_customer_type(order)
    for rule in rules:
        if not rule_matches(rule, context):
            continue
        actions = tuple(
            _dataset_action(a, context)
            for a in sorted(
                (a for a in rule.actions.all() if a.is_active),
                key=lambda i: (i.priority, i.id),
            )
        )
        base = ResolvedOrderRule.from_rule(rule=rule, customer_type=customer_type)
        return replace(base, dataset_actions=actions)
    return ResolvedOrderRule(customer_type=customer_type)


__all__ = ["resolve_order_rule", "detect_customer_type", "ORDER_CREATE_TASK"]
