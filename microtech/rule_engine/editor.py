"""Serialisation of Microtech order rules into edit-JSON for the interactive rule editor.

Turns a ``MicrotechOrderRule`` (with its nested condition-group tree and actions)
into a plain dict the editor UI can load into its form state. Purely a read path;
does not evaluate, apply, or mutate anything. See ``microtech/rule_engine/overview.py``
for the sibling read-only overview serializer.
"""
from __future__ import annotations

from django.db import transaction

from microtech.models import (
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleOperator,
    RuleTrigger,
)


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


class EditorValidationError(Exception):
    """Raised when an edit-JSON payload fails validation in ``save_rule_from_payload``.

    Carries every violation found (not just the first) in ``.messages`` so the
    editor UI can surface them all at once.
    """

    def __init__(self, messages: list[str]):
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


def _validate_payload(payload: dict) -> list[str]:
    errors: list[str] = []

    valid_phases = {code for code, _label in MicrotechOrderRule.ExecutionPhase.choices}
    execution_phase = payload.get("execution_phase")
    if execution_phase not in valid_phases:
        errors.append(f"Ungueltige execution_phase: {execution_phase!r}")

    trigger_id = payload.get("trigger_id")
    if trigger_id is not None and not RuleTrigger.objects.filter(pk=trigger_id).exists():
        errors.append(f"Trigger existiert nicht: {trigger_id!r}")

    active_operator_codes = set(
        MicrotechOrderRuleOperator.objects.filter(is_active=True).values_list("code", flat=True)
    )

    valid_logic_values = {code for code, _label in MicrotechOrderRule.ConditionLogic.choices}

    def _walk_group(group_payload) -> None:
        if not group_payload:
            return
        if not isinstance(group_payload, dict):
            errors.append(f"Ungueltige Gruppen-Struktur: {group_payload!r}")
            return
        logic = group_payload.get("logic")
        if logic not in valid_logic_values:
            errors.append(f"Ungueltige logic: {logic!r}")
        for condition in group_payload.get("conditions", []) or []:
            operator_code = condition.get("operator_code")
            if operator_code not in active_operator_codes:
                errors.append(f"Ungueltiger operator_code: {operator_code!r}")
        for child in group_payload.get("children", []) or []:
            _walk_group(child)

    _walk_group(payload.get("root_group"))

    valid_action_types = {code for code, _label in MicrotechOrderRuleAction.ActionType.choices}
    for action in payload.get("actions", []) or []:
        action_type = action.get("action_type")
        if action_type not in valid_action_types:
            errors.append(f"Ungueltiger action_type: {action_type!r}")
            continue
        if action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD:
            dataset_field_id = action.get("dataset_field_id")
            if not dataset_field_id:
                errors.append("set_field-Aktion benoetigt dataset_field_id")
            elif not MicrotechDatasetField.objects.filter(pk=dataset_field_id).exists():
                errors.append(f"Dataset-Feld existiert nicht: {dataset_field_id!r}")

    return errors


def _fill_group(rule: MicrotechOrderRule, group, group_payload: dict) -> None:
    for priority, condition_payload in enumerate(group_payload.get("conditions", []) or []):
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            group=group,
            priority=priority,
            django_field_path=condition_payload.get("field_path", ""),
            operator_code=condition_payload.get("operator_code", ""),
            expected_value=condition_payload.get("expected_value", ""),
            expected_value_2=condition_payload.get("expected_value_2", ""),
        )
    for priority, child_payload in enumerate(group_payload.get("children", []) or []):
        child_group = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule,
            parent=group,
            priority=priority,
            logic=child_payload.get("logic", MicrotechOrderRule.ConditionLogic.ALL),
        )
        _fill_group(rule, child_group, child_payload)


def save_rule_from_payload(payload: dict, *, rule: MicrotechOrderRule | None = None) -> MicrotechOrderRule:
    """Persist edit-JSON ``payload`` (see ``serialize_rule_for_edit``) as a ``MicrotechOrderRule``.

    Creates a new rule when ``rule`` is ``None``, otherwise updates the given
    rule in place. The rule's entire condition-group tree and action list are
    replaced (existing ones deleted, then recreated from ``payload``). Runs in
    a single ``transaction.atomic`` block: any validation failure raises
    ``EditorValidationError`` and leaves the database untouched.
    """
    errors = _validate_payload(payload)
    if errors:
        raise EditorValidationError(errors)

    with transaction.atomic():
        if rule is None:
            rule = MicrotechOrderRule()

        rule.name = payload.get("name", "")
        rule.priority = payload.get("priority", 100)
        rule.is_active = payload.get("is_active", True)
        rule.execution_phase = payload.get("execution_phase")
        rule.engine_enabled = payload.get("engine_enabled", False)
        rule.shadow_mode = payload.get("shadow_mode", True)
        rule.trigger_id = payload.get("trigger_id")
        rule.save()

        rule.condition_groups.all().delete()
        rule.actions.all().delete()

        root_group = payload.get("root_group")
        if root_group:
            _fill_group(rule, MicrotechOrderRuleConditionGroup.objects.create(
                rule=rule, parent=None, logic=root_group.get("logic", MicrotechOrderRule.ConditionLogic.ALL),
            ), root_group)

        for priority, action_payload in enumerate(payload.get("actions", []) or []):
            MicrotechOrderRuleAction.objects.create(
                rule=rule,
                priority=priority,
                action_type=action_payload.get("action_type"),
                dataset_field_id=action_payload.get("dataset_field_id"),
                target_value=action_payload.get("target_value", ""),
            )

    return rule


__all__ = ["serialize_rule_for_edit", "save_rule_from_payload", "EditorValidationError"]
