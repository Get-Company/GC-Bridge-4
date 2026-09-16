"""Resolve address output fields (e.g. Na1) from address-write rules.

Evaluates every matching ``address_write`` rule against a single
``customer.Address`` in priority order.  Later actions for the same field
override earlier values; actions for different fields are accumulated.
"""
from __future__ import annotations

from microtech.models import MicrotechOrderRuleAction
from microtech.rule_engine.execution import RuleExecutionService

ADDRESS_WRITE_TASK = "customer.microtech_postal_address"


def resolve_address_fields(address) -> dict[str, str]:
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=ADDRESS_WRITE_TASK,
        phase="before",
        root_instance=address,
    )
    return {
        action.field_path: action.value
        for match in matches
        for action in match.actions
        if action.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.field_path
    }


__all__ = ["resolve_address_fields", "ADDRESS_WRITE_TASK"]
