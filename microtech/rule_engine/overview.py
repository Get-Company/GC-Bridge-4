"""Read-only serialisation of Microtech order rules for the graphical builder overview.

Turns a ``MicrotechOrderRule`` (with its nested condition-group tree and actions)
into plain dicts the admin template renders as vertical blocks. Purely presentational;
does not evaluate or apply anything.
"""
from __future__ import annotations

import re

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleOperator
from microtech.rule_builder import get_django_field_map

_VARIABLE_PATTERN = re.compile(r"\{\{.*?\}\}")

_VALUELESS_OPERATORS = {"is_empty", "is_not_empty", "is_true", "is_false"}


def _field_label(path: str, field_map: dict) -> str:
    path = str(path or "").strip()
    if not path:
        return "?"
    field_def = field_map.get(path)
    label = str(getattr(field_def, "label", "") or "").strip() if field_def else ""
    return label or path


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
    if action.dataset_field_id:
        try:
            field_name = str(action.dataset_field.field_name or "")
        except Exception:
            field_name = ""
    target = str(action.target_value or "")
    return {
        "kind": "action",
        "type_code": action_type,
        "type_label": action.get_action_type_display(),
        "field": field_name,
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
    }


def serialize_rules_for_overview() -> list[dict]:
    """Serialise all order rules (active first, by priority) for the overview page."""
    field_map = get_django_field_map()
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
    return [serialize_rule(rule, field_map, operator_map) for rule in rules]


__all__ = ["serialize_rule", "serialize_rules_for_overview"]
