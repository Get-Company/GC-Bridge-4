"""Build the ``ResolvedOrderRule`` contract from the new rule engine.

All matching active rules contribute their actions in priority order.  The
return type is the same ``ResolvedOrderRule`` the Microtech upsert already
consumes, so no downstream change is required.
"""
from __future__ import annotations

from dataclasses import replace

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.execution import RuleExecutionService
from orders.services.order_rule_resolver import (
    ResolvedDatasetAction,
    ResolvedOrderRule,
    detect_customer_type as _detect_customer_type,
)

ORDER_CREATE_TASK = "orders.microtech_order_upsert"


def detect_customer_type(order) -> str:
    return _detect_customer_type(order=order)


def _dataset_action(action) -> ResolvedDatasetAction:
    if action.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.dataset_field_name:
        return ResolvedDatasetAction(
            action_type=action.action_type,
            dataset_source_identifier=action.dataset_source_identifier,
            dataset_name=action.dataset_name,
            dataset_field_name=action.dataset_field_name,
            dataset_field_type=action.dataset_field_type,
            target_value=action.value,
        )
    return ResolvedDatasetAction(action_type=action.action_type, target_value=action.value)


def resolve_order_rule(order) -> ResolvedOrderRule:
    customer_type = detect_customer_type(order)
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=ORDER_CREATE_TASK,
        phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
        root_instance=order,
    )
    if matches:
        actions = tuple(
            _dataset_action(action)
            for match in matches
            for action in match.actions
        )
        # Retain the first matching rule in the legacy-compatible debug fields;
        # ``dataset_actions`` contains the actions from every matching rule.
        base = ResolvedOrderRule.from_rule(rule=matches[0].rule, customer_type=customer_type)
        return replace(base, dataset_actions=actions)
    return ResolvedOrderRule(customer_type=customer_type)


__all__ = ["resolve_order_rule", "detect_customer_type", "ORDER_CREATE_TASK"]
