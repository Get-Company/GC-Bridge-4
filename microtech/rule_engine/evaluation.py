from __future__ import annotations

from microtech.models import MicrotechOrderRule
from microtech.rule_builder import get_django_field_map, get_operator_engine_map
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.operators import evaluate_operator
from microtech.rule_engine.templates import render_template


def _value_kind_for(field_path, field_map) -> str:
    field_def = field_map.get(field_path)
    return str(getattr(field_def, "value_kind", "string") or "string") if field_def else "string"


def _evaluate_condition(condition, context, field_map, operator_engine_map) -> bool:
    field_path = str(condition.django_field_path or "")
    value_kind = _value_kind_for(field_path, field_map)
    engine_op = str(operator_engine_map.get(condition.operator_code) or condition.operator_code or "")
    actual = context.get(field_path)
    expected = render_template(condition.expected_value or "", context)
    expected_2 = render_template(condition.expected_value_2 or "", context)
    return evaluate_operator(engine_op, actual, expected, expected_2, value_kind)


def evaluate_group(group, context, *, field_map=None, operator_engine_map=None) -> bool:
    field_map = field_map or get_django_field_map()
    operator_engine_map = operator_engine_map or get_operator_engine_map()

    active_conditions = [c for c in group.conditions.all() if c.is_active]
    active_children = [g for g in group.children.all() if g.is_active]

    results = [
        _evaluate_condition(c, context, field_map, operator_engine_map)
        for c in sorted(active_conditions, key=lambda i: (i.priority, i.id))
    ]
    results += [
        evaluate_group(child, context, field_map=field_map, operator_engine_map=operator_engine_map)
        for child in sorted(active_children, key=lambda i: (i.priority, i.id))
    ]

    if not results:
        return True  # leere Gruppe = neutral (globaler Fallback)
    if group.logic == MicrotechOrderRule.ConditionLogic.ANY:
        return any(results)
    return all(results)


def rule_matches(rule, context) -> bool:
    roots = [g for g in rule.condition_groups.all() if g.is_active and g.parent_id is None]
    if not roots:
        return True
    field_map = get_django_field_map()
    operator_engine_map = get_operator_engine_map()
    return all(
        evaluate_group(root, context, field_map=field_map, operator_engine_map=operator_engine_map)
        for root in roots
    )
