"""Resolve CustomerInput fields from customer-write rules.

Generic: returns the ``set_field`` actions of every matching rule as a
``{graphql_field_name: value}`` map.  Rules run in priority order; a later
action for the same field overrides an earlier value.  Conditions are evaluated
against the tax address (billing address or the address itself), so rules can
test e.g. ``country_code``.
"""
from __future__ import annotations

from microtech.models import MicrotechOrderRuleAction
from microtech.rule_engine.execution import RuleExecutionService

CUSTOMER_WRITE_TASK = "customer.microtech_customer_upsert"


def resolve_customer_fields(*, customer, address, billing_address=None) -> dict[str, str]:
    tax_address = billing_address or address
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=CUSTOMER_WRITE_TASK,
        phase="before",
        root_instance=tax_address,
    )
    return {
        action.field_path: action.value
        for match in matches
        for action in match.actions
        if action.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.field_path
    }


__all__ = ["resolve_customer_fields", "CUSTOMER_WRITE_TASK"]
