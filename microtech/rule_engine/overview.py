"""Read-only serialisation of Microtech order rules for the graphical builder overview.

Turns a ``MicrotechOrderRule`` (with its nested condition-group tree and actions)
into plain dicts the admin template renders as vertical blocks. Purely presentational;
does not evaluate or apply anything.
"""
from __future__ import annotations

import re

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleOperator
from microtech.rule_builder import (
    get_address_field_defs,
    get_customer_field_defs,
    get_django_field_map,
)
from microtech.rule_engine.editor import serialize_rule_for_edit

_VARIABLE_PATTERN = re.compile(r"\{\{.*?\}\}")

_VALUELESS_OPERATORS = {"is_empty", "is_not_empty", "is_true", "is_false"}


def _field_label(path: str, field_map: dict) -> str:
    path = str(path or "").strip()
    if not path:
        return "?"
    field_def = field_map.get(path)
    label = str(getattr(field_def, "label", "") or "").strip() if field_def else ""
    if not label or label == path:
        return path
    return f"{label} · {path}"


def _operator_label(code: str, operator_map: dict) -> str:
    code = str(code or "").strip()
    return operator_map.get(code, code) or "?"


def _looks_like_variable(value: str) -> bool:
    return bool(_VARIABLE_PATTERN.search(str(value or "")))


def _serialize_condition(condition, field_map: dict, operator_map: dict) -> dict:
    code = str(condition.operator_code or "")
    value = str(condition.expected_value or "")
    value_2 = str(condition.expected_value_2 or "")
    if code == "between":
        value_display = f"{value} … {value_2}" if (value or value_2) else ""
    elif code in _VALUELESS_OPERATORS:
        value_display = ""
    else:
        value_display = value
    return {
        "kind": "condition",
        "field": _field_label(condition.django_field_path, field_map),
        "operator": _operator_label(code, operator_map),
        "value": value_display,
        "value_is_variable": _looks_like_variable(value),
        "is_active": condition.is_active,
    }


def _serialize_group(group, field_map: dict, operator_map: dict) -> dict:
    conditions = [
        _serialize_condition(c, field_map, operator_map)
        for c in sorted(
            (c for c in group.conditions.all() if c.is_active),
            key=lambda i: (i.priority, i.id),
        )
    ]
    children = [
        _serialize_group(child, field_map, operator_map)
        for child in sorted(
            (g for g in group.children.all() if g.is_active),
            key=lambda i: (i.priority, i.id),
        )
    ]
    return {
        "kind": "group",
        "logic": group.get_logic_display(),
        "logic_code": group.logic,
        "conditions": conditions,
        "children": children,
        "is_empty": not conditions and not children,
    }


def _serialize_action(action) -> dict:
    action_type = str(action.action_type or "")
    field_name = ""
    field_title = ""
    if action.dataset_field_id:
        try:
            dataset_field = action.dataset_field
            dataset_name = str(dataset_field.dataset.name or "Microtech")
            technical_name = f"{dataset_name}.{dataset_field.field_name}"
            label = str(dataset_field.label or dataset_field.field_name or "")
            field_name = (
                f"{label} · {technical_name}"
                if label and label != technical_name
                else technical_name
            )
            field_title = field_name
        except Exception:
            field_name = ""
    elif action.graphql_field:
        graphql_field = str(action.graphql_field)
        field_name = f"{graphql_field.rsplit('.', 1)[-1]} · {graphql_field}"
        target_scope = action.target_scope or "customer"
        if target_scope != "customer":
            scope_label = str(action.get_target_scope_display() or target_scope)
            field_name = f"{scope_label} · {field_name}"
        field_title = field_name
    target = str(action.target_value or "")
    return {
        "kind": "action",
        "type_code": action_type,
        "type_label": action.get_action_type_display(),
        "field": field_name,
        "field_title": field_title,
        "value": target,
        "value_is_variable": _looks_like_variable(target),
        "is_active": action.is_active,
    }


def serialize_rule(rule, field_map: dict, operator_map: dict) -> dict:
    root_groups = [
        _serialize_group(g, field_map, operator_map)
        for g in sorted(
            (g for g in rule.condition_groups.all() if g.is_active and g.parent_id is None),
            key=lambda i: (i.priority, i.id),
        )
    ]
    actions = [
        _serialize_action(a)
        for a in sorted(
            (a for a in rule.actions.all() if a.is_active),
            key=lambda i: (i.priority, i.id),
        )
    ]
    trigger = None
    if rule.trigger_id:
        try:
            trigger = {
                "label": rule.trigger.label,
                "code": rule.trigger.code,
                "task_name": rule.trigger.task_name,
                "context_root": rule.trigger.context_root,
            }
        except Exception:
            trigger = None
    return {
        "id": rule.pk,
        "name": rule.name,
        "priority": rule.priority,
        "is_active": rule.is_active,
        "engine_enabled": rule.engine_enabled,
        "shadow_mode": rule.shadow_mode,
        "execution_phase": rule.get_execution_phase_display(),
        "trigger": trigger,
        "root_groups": root_groups,
        "actions": actions,
        "has_conditions": any(not g["is_empty"] for g in root_groups),
        "edit_json": serialize_rule_for_edit(rule),
    }


def serialize_rules_for_overview() -> list[dict]:
    """Serialise all order rules (active first, by priority) for the overview page."""
    order_field_map = get_django_field_map()
    address_field_map = {item.path: item for item in get_address_field_defs("customer.Address")}
    customer_field_map = {item.path: item for item in get_customer_field_defs()}
    operator_map = {
        op.code: op.name
        for op in MicrotechOrderRuleOperator.objects.all()
    }
    rules = (
        MicrotechOrderRule.objects
        .prefetch_related(
            "condition_groups",
            "condition_groups__conditions",
            "condition_groups__children",
            "actions",
            "actions__dataset_field",
        )
        .select_related("trigger")
        .order_by("-is_active", "priority", "id")
    )
    field_map_by_context_root = {
        "customer.Address": address_field_map,
        "customer.Customer": customer_field_map,
    }
    return [
        serialize_rule(
            rule,
            field_map_by_context_root.get(
                str(getattr(rule.trigger, "context_root", "") or ""),
                order_field_map,
            ),
            operator_map,
        )
        for rule in rules
    ]


__all__ = ["serialize_rule", "serialize_rules_for_overview"]
