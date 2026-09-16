"""Resolve address output fields (e.g. Na1) from address-write rules.

Evaluates active ``address_write`` rules against a single ``customer.Address``
and returns the ``set_field`` actions of the first matching rule as a
``{dataset_field_name: value}`` map (values rendered through the template layer).
"""
from __future__ import annotations

from microtech.models import MicrotechOrderRuleAction
from microtech.rule_engine.execution import RuleExecutionService

ADDRESS_WRITE_TASK = "customer.microtech_postal_address"


def resolve_address_fields(address) -> dict[str, str]:
    match = RuleExecutionService().resolve_first_match(
        task_name=ADDRESS_WRITE_TASK,
        phase="before",
        root_instance=address,
    )
    if match is None:
        return {}
    return {
        action.field_path: action.value
        for action in match.actions
        if action.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.field_path
    }


__all__ = ["resolve_address_fields", "ADDRESS_WRITE_TASK"]
