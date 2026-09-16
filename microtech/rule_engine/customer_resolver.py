"""Resolve CustomerInput fields from customer-write rules.

Generic: returns the ``set_field`` actions of the first matching rule as a
``{graphql_field_name: value}`` map, so overlaying it onto the GraphQL customer
input covers *every* CustomerInput field at once (taxCategory, name1, …) — no
per-field wiring. Conditions are evaluated against the tax address (billing
address or the address itself), so rules can test e.g. ``country_code``.
"""
from __future__ import annotations

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.address_resolver import _target_field_name
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template

CUSTOMER_WRITE_TASK = "customer.microtech_customer_upsert"


def resolve_customer_fields(*, customer, address, billing_address=None) -> dict[str, str]:
    tax_address = billing_address or address
    context = EvaluationContext(tax_address)
    rules = (
        MicrotechOrderRule.objects
        .filter(
            is_active=True,
            engine_enabled=True,
            execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
            trigger__task_name=CUSTOMER_WRITE_TASK,
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
            field_name = _target_field_name(action)
            if not field_name:
                continue
            result[field_name] = render_template(action.target_value or "", context)
        return result
    return {}


__all__ = ["resolve_customer_fields", "CUSTOMER_WRITE_TASK"]
