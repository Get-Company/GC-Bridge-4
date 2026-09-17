from __future__ import annotations

from microtech.models import MicrotechOrderRule
from microtech.rule_builder import get_django_field_map, get_operator_engine_map
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.operators import evaluate_operator
from microtech.rule_engine.templates import render_template


def _value_kind_for(field_path, field_map) -> str:
    field_def = field_map.get(field_path)
    return str(getattr(field_def, "value_kind", "string") or "string") if field_def else "string"


def _evaluate_condition(condition, context, field_map, operator_engine_map, *, strict_fields: bool) -> bool:
    field_path = str(condition.django_field_path or "")
    if strict_fields and field_path not in field_map:
        return False
    value_kind = _value_kind_for(field_path, field_map)
    engine_op = str(operator_engine_map.get(condition.operator_code) or "")
    if not engine_op:
        return False
    actual = context.get(field_path)
    expected = render_template(condition.expected_value or "", context)
    expected_2 = render_template(condition.expected_value_2 or "", context)
    return evaluate_operator(engine_op, actual, expected, expected_2, value_kind)


def evaluate_group(group, context, *, field_map=None, operator_engine_map=None, strict_fields=False) -> bool:
    field_map = field_map or get_django_field_map()
    operator_engine_map = operator_engine_map or get_operator_engine_map()

    active_conditions = [c for c in group.conditions.all() if c.is_active]
    active_children = [g for g in group.children.all() if g.is_active]

    results = [
        _evaluate_condition(c, context, field_map, operator_engine_map, strict_fields=strict_fields)
        for c in sorted(active_conditions, key=lambda i: (i.priority, i.id))
    ]
    results += [
        evaluate_group(
            child,
            context,
            field_map=field_map,
            operator_engine_map=operator_engine_map,
            strict_fields=strict_fields,
        )
        for child in sorted(active_children, key=lambda i: (i.priority, i.id))
    ]

    if not results:
        return True  # leere Gruppe = neutral (globaler Fallback)
    if group.logic == MicrotechOrderRule.ConditionLogic.ANY:
        return any(results)
    return all(results)


def rule_matches(rule, context, *, field_map=None, operator_engine_map=None) -> bool:
    roots = [g for g in rule.condition_groups.all() if g.is_active and g.parent_id is None]
    if not roots:
        # Ungrouped conditions are legacy data.  Treating such a rule as a
        # global fallback in the new engine would silently bypass its filters.
        return not any(condition.is_active for condition in rule.conditions.all())
    strict_fields = field_map is not None
    field_map = field_map or get_django_field_map()
    operator_engine_map = operator_engine_map or get_operator_engine_map()
    return all(
        evaluate_group(
            root,
            context,
            field_map=field_map,
            operator_engine_map=operator_engine_map,
            strict_fields=strict_fields,
        )
        for root in roots
    )


def rule_condition_results(rule, context, *, field_map=None, operator_engine_map=None) -> tuple[dict, ...]:
    """Return each active condition's result without exposing the source value."""
    field_map = field_map or get_django_field_map()
    operator_engine_map = operator_engine_map or get_operator_engine_map()
    strict_fields = field_map is not None
    return tuple(
        {
            "field": str(condition.django_field_path or ""),
            "operator": str(condition.operator_code or ""),
            "expected": render_template(condition.expected_value or "", context),
            "expected_2": render_template(condition.expected_value_2 or "", context),
            "matched": _evaluate_condition(
                condition,
                context,
                field_map,
                operator_engine_map,
                strict_fields=strict_fields,
            ),
        }
        for condition in sorted(
            (item for item in rule.conditions.all() if item.is_active),
            key=lambda item: (item.priority, item.id),
        )
    )
