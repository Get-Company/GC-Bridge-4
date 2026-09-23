"""Apply the editable standard mapping rules to precomputed code values."""
from __future__ import annotations

from dataclasses import dataclass

from microtech.graphql_schema import get_rule_action_input_types
from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.customer_resolver import CustomerRuleContext
from microtech.rule_engine.execution import RuleExecutionService

ORDER_MAPPING_TASK = "orders.microtech_order_mapping"
ORDER_POSITION_MAPPING_TASK = "orders.microtech_order_position_mapping"
CUSTOMER_MAPPING_TASK = "customer.microtech_customer_mapping"


@dataclass(frozen=True, slots=True)
class OrderMappingContext:
    order: object
    code_values: dict

    def __getattr__(self, name: str):
        return getattr(self.order, name)


@dataclass(frozen=True, slots=True)
class OrderPositionMappingContext:
    detail: object
    code_values: dict

    def __getattr__(self, name: str):
        return getattr(self.detail, name)


def _coerce_like_code_value(*, field_name: str, value: str, code_values: dict):
    code_value = code_values.get(field_name)
    if isinstance(code_value, bool):
        return str(value or "").strip().lower() in {"1", "true", "yes", "ja", "on"}
    if isinstance(code_value, int):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return value
    return value


def _resolve_mapping_fields(
    *,
    task_name: str,
    root_instance: object,
    code_values: dict,
    target_scope: str | None = None,
) -> dict:
    allowed_input_types = get_rule_action_input_types(task_name, target_scope or "")
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=task_name,
        phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
        root_instance=root_instance,
        action_scope=target_scope,
    )
    resolved: dict = {}
    for match in matches:
        for action in match.actions:
            if (
                action.action_type != MicrotechOrderRuleAction.ActionType.SET_FIELD
                or not action.field_path
            ):
                continue
            if allowed_input_types and action.graphql_field.split(".", 1)[0] not in allowed_input_types:
                continue
            resolved[action.field_path] = _coerce_like_code_value(
                field_name=action.field_path,
                value=action.value,
                code_values=code_values,
            )
    return resolved


def resolve_order_mapping_fields(*, order, code_values: dict) -> dict:
    return _resolve_mapping_fields(
        task_name=ORDER_MAPPING_TASK,
        root_instance=OrderMappingContext(order=order, code_values=code_values),
        code_values=code_values,
        target_scope=MicrotechOrderRuleAction.TargetScope.ORDER,
    )


def resolve_order_position_mapping_fields(*, detail, code_values: dict) -> dict:
    return _resolve_mapping_fields(
        task_name=ORDER_POSITION_MAPPING_TASK,
        root_instance=OrderPositionMappingContext(detail=detail, code_values=code_values),
        code_values=code_values,
        target_scope=MicrotechOrderRuleAction.TargetScope.POSITION,
    )


def resolve_customer_mapping_fields(
    *,
    customer,
    shipping_address,
    billing_address,
    address,
    target_scope: str,
    code_values: dict,
) -> dict:
    return _resolve_mapping_fields(
        task_name=CUSTOMER_MAPPING_TASK,
        root_instance=CustomerRuleContext(
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            address=address,
            code_values=code_values,
        ),
        code_values=code_values,
        target_scope=target_scope,
    )


__all__ = [
    "CUSTOMER_MAPPING_TASK",
    "ORDER_MAPPING_TASK",
    "ORDER_POSITION_MAPPING_TASK",
    "resolve_customer_mapping_fields",
    "resolve_order_mapping_fields",
    "resolve_order_position_mapping_fields",
]
