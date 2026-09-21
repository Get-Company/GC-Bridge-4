"""Resolve CustomerInput fields from customer-write rules."""
from __future__ import annotations

from dataclasses import dataclass

from microtech.models import MicrotechOrderRuleAction
from microtech.graphql_schema import get_rule_action_input_types
from microtech.rule_engine.execution import RuleExecutionService

CUSTOMER_WRITE_TASK = "customer.microtech_customer_upsert"


@dataclass(frozen=True, slots=True)
class CustomerRuleContext:
    """Explicit customer context with independent invoice and delivery paths."""

    customer: object
    shipping_address: object | None
    billing_address: object | None
    address: object | None = None


def resolve_customer_scope_fields(
    *,
    customer,
    shipping_address,
    billing_address,
    address,
    target_scope: str,
    audit_mode: str | None = None,
) -> dict[str, str]:
    """Resolve fields for one concrete customer-upsert destination.

    ``address`` is the current write target.  The independent
    ``shipping_address`` and ``billing_address`` paths remain available in
    templates and rule conditions, while ``address__`` is intentionally the
    concrete target selected through ``target_scope``.
    """
    allowed_input_types = get_rule_action_input_types(CUSTOMER_WRITE_TASK, target_scope)
    if not allowed_input_types:
        return {}
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=CUSTOMER_WRITE_TASK,
        phase="before",
        root_instance=CustomerRuleContext(
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            address=address,
        ),
        audit_mode=audit_mode,
        audit_subject=f"Kunde #{getattr(customer, 'pk', '') or '?'}",
        action_scope=target_scope,
    )
    return {
        action.field_path: action.value
        for match in matches
        for action in match.actions
        if action.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.field_path
        and action.graphql_field.split(".", 1)[0] in allowed_input_types
    }


def resolve_customer_fields(*, customer, address, billing_address=None, audit_mode: str | None = None) -> dict[str, str]:
    """Backward-compatible resolver for the CustomerInput destination."""
    return resolve_customer_scope_fields(
        customer=customer,
        shipping_address=address,
        billing_address=billing_address,
        address=address,
        target_scope=MicrotechOrderRuleAction.TargetScope.CUSTOMER,
        audit_mode=audit_mode,
    )


__all__ = [
    "CustomerRuleContext",
    "resolve_customer_fields",
    "resolve_customer_scope_fields",
    "CUSTOMER_WRITE_TASK",
]
