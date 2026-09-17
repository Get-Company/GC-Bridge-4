"""Resolve CustomerInput fields from customer-write rules."""
from __future__ import annotations

from dataclasses import dataclass

from microtech.models import MicrotechOrderRuleAction
from microtech.rule_engine.execution import RuleExecutionService

CUSTOMER_WRITE_TASK = "customer.microtech_customer_upsert"


@dataclass(frozen=True, slots=True)
class CustomerRuleContext:
    """Explicit customer context with independent invoice and delivery paths."""

    customer: object
    shipping_address: object | None
    billing_address: object | None


def resolve_customer_fields(*, customer, address, billing_address=None) -> dict[str, str]:
    """Resolve fields using explicit ``billing_address__`` / ``shipping_address__`` paths.

    ``address`` is the shipping address kept for backwards-compatible callers;
    it is never used as an implicit substitute for ``billing_address``.
    """
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=CUSTOMER_WRITE_TASK,
        phase="before",
        root_instance=CustomerRuleContext(
            customer=customer,
            shipping_address=address,
            billing_address=billing_address,
        ),
    )
    return {
        action.field_path: action.value
        for match in matches
        for action in match.actions
        if action.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.field_path
    }


__all__ = ["CustomerRuleContext", "resolve_customer_fields", "CUSTOMER_WRITE_TASK"]
