"""Serialisation of Microtech order rules into edit-JSON for the interactive rule editor.

Turns a ``MicrotechOrderRule`` (with its nested condition-group tree and actions)
into a plain dict the editor UI can load into its form state. Purely a read path;
does not evaluate, apply, or mutate anything. See ``microtech/rule_engine/overview.py``
for the sibling read-only overview serializer.
"""
from __future__ import annotations

from microtech.models import MicrotechOrderRule


def _serialize_condition(condition) -> dict:
    return {
        "field_path": condition.django_field_path,
        "operator_code": condition.operator_code,
        "expected_value": condition.expected_value,
        "expected_value_2": condition.expected_value_2,
    }


def _serialize_group(group) -> dict:
    conditions = [
        _serialize_condition(c)
        for c in sorted(
            (c for c in group.conditions.all() if c.is_active),
            key=lambda i: (i.priority, i.id),
        )
    ]
    children = [
        _serialize_group(child)
        for child in sorted(
            (g for g in group.children.all() if g.is_active),
            key=lambda i: (i.priority, i.id),
        )
    ]
    return {
        "logic": group.logic,
        "children": children,
        "conditions": conditions,
    }


def _serialize_action(action) -> dict:
    return {
        "action_type": action.action_type,
        "dataset_field_id": action.dataset_field_id,
        "target_value": action.target_value,
    }


def serialize_rule_for_edit(rule) -> dict:
    """Serialise ``rule`` into edit-JSON for the interactive rule editor.

    ``root_group`` is the single active root condition group (``parent_id is
    None``); if a rule has no root group at all, ``root_group`` is ``None``.
    """
    root_groups = sorted(
        (g for g in rule.condition_groups.all() if g.is_active and g.parent_id is None),
        key=lambda i: (i.priority, i.id),
    )
    root_group = _serialize_group(root_groups[0]) if root_groups else None

    actions = [
        _serialize_action(a)
        for a in sorted(
            (a for a in rule.actions.all() if a.is_active),
            key=lambda i: (i.priority, i.id),
        )
    ]

    return {
        "id": rule.pk,
        "name": rule.name,
        "priority": rule.priority,
        "is_active": rule.is_active,
        "execution_phase": rule.execution_phase,
        "engine_enabled": rule.engine_enabled,
        "shadow_mode": rule.shadow_mode,
        "trigger_id": rule.trigger_id,
        "root_group": root_group,
        "actions": actions,
    }


__all__ = ["serialize_rule_for_edit"]
