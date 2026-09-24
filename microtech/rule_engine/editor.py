"""Serialisation of Microtech order rules into edit-JSON for the interactive rule editor.

Turns a ``MicrotechOrderRule`` (with its nested condition-group tree and actions)
into a plain dict the editor UI can load into its form state. Purely a read path;
does not evaluate, apply, or mutate anything. See ``microtech/rule_engine/overview.py``
for the sibling read-only overview serializer.
"""
from __future__ import annotations

import re

from django.db import transaction

from microtech.models import (
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCategory,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleOperator,
    RuleTrigger,
)
from microtech.graphql_schema import (
    get_rule_action_excluded_fields,
    get_rule_action_input_types,
    get_rule_action_scopes,
    get_rule_trigger_input_types,
)
from microtech.rule_comparisons import to_bool, to_date, to_datetime, to_decimal
from microtech.rule_builder import (
    get_address_field_defs,
    get_allowed_operator_codes,
    get_customer_field_defs,
    get_django_field_map,
    get_order_detail_field_defs,
    get_operator_engine_map,
)
from microtech.rule_engine.templates import TemplateValidationError, validate_template
from microtech.rule_field_labels import microtech_field_ui_label


_ADDRESS_CONTEXT_ROOTS = {"customer.Address"}
_CUSTOMER_CONTEXT_ROOT = "customer.Customer"
_ORDER_DETAIL_CONTEXT_ROOT = "orders.OrderDetail"
_VALUELESS_OPERATORS = {"is_empty", "is_not_empty", "is_true", "is_false"}
_GRAPHQL_FIELD_PATTERN = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")


def _as_text(value) -> str:
    return "" if value is None else str(value)


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
    dataset_field_label = ""
    if action.dataset_field_id:
        try:
            dataset_field = action.dataset_field
            field_name = str(dataset_field.field_name or "")
            dataset_field_label = microtech_field_ui_label(
                field_name,
                dataset_field.label,
                dataset_name=dataset_field.dataset.name,
            )
        except (AttributeError, MicrotechDatasetField.DoesNotExist):
            # A deleted catalog entry must not prevent an existing rule from
            # opening in the editor. Validation on save reports the missing ID.
            dataset_field_label = ""

    graphql_field = action.graphql_field or ""
    graphql_field_label = ""
    if graphql_field:
        field_name = graphql_field.rsplit(".", 1)[-1]
        graphql_field_label = f"{field_name} (GraphQL)"

    return {
        "action_type": action.action_type,
        "dataset_field_id": action.dataset_field_id,
        "dataset_field_label": dataset_field_label,
        "graphql_field": graphql_field,
        "graphql_field_label": graphql_field_label,
        "target_scope": action.target_scope,
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
    if len(root_groups) == 1:
        root_group = _serialize_group(root_groups[0])
    elif root_groups:
        # Existing data can contain several roots although the editor's
        # contract is one tree.  The evaluator combines roots with AND, so a
        # synthetic ALL root preserves the behaviour when the rule is saved.
        root_group = {
            "logic": MicrotechOrderRule.ConditionLogic.ALL,
            "children": [_serialize_group(group) for group in root_groups],
            "conditions": [],
        }
    else:
        root_group = None

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
        "category_id": rule.category_id,
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


def _validate_payload(
    payload: dict,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["Regel-Payload muss ein JSON-Objekt sein."]

    valid_phases = {code for code, _label in MicrotechOrderRule.ExecutionPhase.choices}
    execution_phase = payload.get("execution_phase")
    if execution_phase not in valid_phases:
        errors.append(f"Ungueltige execution_phase: {execution_phase!r}")

    trigger_id = payload.get("trigger_id")
    trigger = None
    if trigger_id is not None:
        trigger = RuleTrigger.objects.filter(pk=trigger_id).first()
        if trigger is None:
            errors.append(f"Trigger existiert nicht: {trigger_id!r}")

    category_id = payload.get("category_id")
    if category_id is not None and not MicrotechOrderRuleCategory.objects.filter(
        pk=category_id,
        is_active=True,
    ).exists():
        errors.append(f"Kategorie existiert nicht: {category_id!r}")

    if trigger is not None and trigger.context_root in _ADDRESS_CONTEXT_ROOTS:
        field_map = {item.path: item for item in get_address_field_defs(trigger.context_root)}
    elif trigger is not None and trigger.context_root == _CUSTOMER_CONTEXT_ROOT:
        field_map = {item.path: item for item in get_customer_field_defs()}
    elif trigger is not None and trigger.context_root == _ORDER_DETAIL_CONTEXT_ROOT:
        field_map = {item.path: item for item in get_order_detail_field_defs()}
    else:
        field_map = get_django_field_map()
    allowed_paths = set(field_map)
    operator_engine_map = get_operator_engine_map()

    active_operator_codes = set(
        MicrotechOrderRuleOperator.objects.filter(is_active=True).values_list("code", flat=True)
    )

    valid_logic_values = {code for code, _label in MicrotechOrderRule.ConditionLogic.choices}

    def _validate_template_value(value, *, label: str) -> bool:
        try:
            validate_template(_as_text(value), allowed_paths=allowed_paths)
        except TemplateValidationError as exc:
            errors.append(f"{label}: {exc}")
            return False
        return True

    def _validate_condition_values(*, engine_operator: str, value_kind: str, first, second, label: str) -> None:
        first_value = _as_text(first).strip()
        second_value = _as_text(second).strip()
        if engine_operator in _VALUELESS_OPERATORS:
            return
        if not first_value:
            errors.append(f"{label}: Vergleichswert darf nicht leer sein.")
            return
        if engine_operator == "between" and not second_value:
            errors.append(f"{label}: Operator 'between' braucht zwei Vergleichswerte.")
            return
        if "{{" in first_value or "{{" in second_value:
            return

        parser = {
            "int": to_decimal,
            "decimal": to_decimal,
            "bool": to_bool,
            "date": to_date,
            "datetime": to_datetime,
        }.get(value_kind)
        if parser is None:
            return
        if parser(first_value) is None:
            errors.append(f"{label}: Vergleichswert passt nicht zum Feldtyp {value_kind}.")
        if engine_operator == "between" and parser(second_value) is None:
            errors.append(f"{label}: zweiter Vergleichswert passt nicht zum Feldtyp {value_kind}.")

    def _walk_group(group_payload, *, location: str = "Bedingung") -> None:
        if not group_payload:
            return
        if not isinstance(group_payload, dict):
            errors.append(f"Ungueltige Gruppen-Struktur: {group_payload!r}")
            return
        logic = group_payload.get("logic")
        if logic not in valid_logic_values:
            errors.append(f"Ungueltige logic: {logic!r}")
        conditions = group_payload.get("conditions", []) or []
        if not isinstance(conditions, list):
            errors.append(f"{location}: conditions muss eine Liste sein.")
            conditions = []
        for position, condition in enumerate(conditions, start=1):
            condition_label = f"{location} {position}"
            if not isinstance(condition, dict):
                errors.append(f"{condition_label}: muss ein Objekt sein.")
                continue
            field_path = str(condition.get("field_path") or "").strip()
            field_def = field_map.get(field_path)
            if field_def is None:
                errors.append(f"{condition_label}: unbekannter Feldpfad {field_path!r}.")
                continue
            operator_code = str(condition.get("operator_code") or "").strip()
            if operator_code not in active_operator_codes:
                errors.append(f"{condition_label}: ungueltiger operator_code {operator_code!r}.")
                continue
            allowed_operator_codes = get_allowed_operator_codes(
                field_path=field_path,
                django_field_map=field_map,
            )
            if operator_code not in allowed_operator_codes:
                errors.append(f"{condition_label}: Operator ist fuer dieses Feld nicht erlaubt.")
                continue
            engine_operator = str(operator_engine_map.get(operator_code) or "")
            if not engine_operator:
                errors.append(f"{condition_label}: Operator hat keine Engine-Implementierung.")
                continue
            first_value = condition.get("expected_value", "")
            second_value = condition.get("expected_value_2", "")
            first_ok = _validate_template_value(first_value, label=condition_label)
            second_ok = _validate_template_value(second_value, label=condition_label)
            if first_ok and second_ok:
                _validate_condition_values(
                    engine_operator=engine_operator,
                    value_kind=str(field_def.value_kind or "string"),
                    first=first_value,
                    second=second_value,
                    label=condition_label,
                )
        children = group_payload.get("children", []) or []
        if not isinstance(children, list):
            errors.append(f"{location}: children muss eine Liste sein.")
            return
        for position, child in enumerate(children, start=1):
            _walk_group(child, location=f"{location}.{position}")

    _walk_group(payload.get("root_group"))

    valid_action_types = {code for code, _label in MicrotechOrderRuleAction.ActionType.choices}
    actions = payload.get("actions", []) or []
    if not isinstance(actions, list):
        errors.append("actions muss eine Liste sein.")
        actions = []
    for position, action in enumerate(actions, start=1):
        action_label = f"Aktion {position}"
        if not isinstance(action, dict):
            errors.append(f"{action_label}: muss ein Objekt sein.")
            continue
        action_type = action.get("action_type")
        if action_type not in valid_action_types:
            errors.append(f"{action_label}: ungueltiger action_type {action_type!r}.")
            continue
        if action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD:
            dataset_field_id = action.get("dataset_field_id")
            graphql_field = str(action.get("graphql_field") or "").strip()
            target_scope = str(
                action.get("target_scope") or MicrotechOrderRuleAction.TargetScope.CUSTOMER
            ).strip()
            scoped_action_defs = get_rule_action_scopes(
                getattr(trigger, "task_name", "")
            )
            if scoped_action_defs and target_scope not in {
                str(item["code"]) for item in scoped_action_defs
            }:
                errors.append(f"{action_label}: ungueltiger Zielbereich {target_scope!r}.")
            if bool(dataset_field_id) == bool(graphql_field):
                errors.append(f"{action_label}: set_field benoetigt genau ein Zielfeld.")
            elif dataset_field_id and not MicrotechDatasetField.objects.filter(
                pk=dataset_field_id, is_active=True, dataset__is_active=True,
            ).exists():
                errors.append(f"{action_label}: Dataset-Feld existiert nicht oder ist inaktiv.")
            elif dataset_field_id and get_rule_trigger_input_types(
                getattr(trigger, "task_name", "")
            ):
                errors.append(
                    f"{action_label}: Dieser Trigger erwartet ein GraphQL-Zielfeld statt eines Dataset-Felds."
                )
            elif graphql_field and not _GRAPHQL_FIELD_PATTERN.fullmatch(graphql_field):
                errors.append(f"{action_label}: ungueltiges GraphQL-Zielfeld {graphql_field!r}.")
            elif graphql_field:
                allowed_input_types = get_rule_action_input_types(
                    getattr(trigger, "task_name", ""), target_scope
                )
                excluded_fields = get_rule_action_excluded_fields(
                    getattr(trigger, "task_name", ""), target_scope
                )
                input_type = graphql_field.split(".", 1)[0]
                if not allowed_input_types:
                    errors.append(
                        f"{action_label}: Der gewaehlte Trigger unterstuetzt keine GraphQL-Zielfelder."
                    )
                elif input_type not in allowed_input_types:
                    errors.append(
                        f"{action_label}: {input_type} ist fuer diesen Trigger nicht erlaubt."
                    )
                elif graphql_field in excluded_fields:
                    errors.append(
                        f"{action_label}: {graphql_field} ist in diesem Zielbereich gesperrt. "
                        "E-Mail muss einer konkreten Anschrift oder einem Ansprechpartner zugeordnet werden."
                    )
        elif action_type == MicrotechOrderRuleAction.ActionType.CREATE_TEXT_POSITION:
            if not str(action.get("target_value") or "").strip():
                errors.append(f"{action_label}: Bezeichnung fuer Textposition ist erforderlich.")
        _validate_template_value(action.get("target_value", ""), label=action_label)

    if (
        payload.get("is_active", True)
        and payload.get("engine_enabled", False)
        and trigger is not None
    ):
        target_positions: dict[str, list[int]] = {}
        for position, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                continue
            if action.get("action_type") != MicrotechOrderRuleAction.ActionType.SET_FIELD:
                continue
            dataset_field_id = action.get("dataset_field_id")
            graphql_field = str(action.get("graphql_field") or "").strip()
            if dataset_field_id:
                target_key = f"dataset:{dataset_field_id}"
            elif graphql_field:
                scope = str(
                    action.get("target_scope")
                    or MicrotechOrderRuleAction.TargetScope.CUSTOMER
                ).strip()
                target_key = f"graphql:{scope}:{graphql_field}"
            else:
                continue
            target_positions.setdefault(target_key, []).append(position)

        for positions in target_positions.values():
            if len(positions) > 1:
                errors.append(
                    "Dasselbe Zielfeld ist mehrfach in dieser Regel belegt "
                    f"(Aktionen {', '.join(str(item) for item in positions)})."
                )

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
        if "category_id" in payload:
            rule.category_id = payload.get("category_id")
        rule.save()

        # Delete ungrouped legacy conditions as well.  Leaving them behind
        # meant a later legacy fallback could evaluate stale conditions after a
        # rule had been edited through the tree editor.
        rule.conditions.all().delete()
        rule.condition_groups.all().delete()
        rule.actions.all().delete()

        root_group = payload.get("root_group")
        if root_group:
            rule.condition_logic = root_group.get("logic", MicrotechOrderRule.ConditionLogic.ALL)
            rule.save(update_fields=["condition_logic", "updated_at"])
            _fill_group(rule, MicrotechOrderRuleConditionGroup.objects.create(
                rule=rule, parent=None, logic=root_group.get("logic", MicrotechOrderRule.ConditionLogic.ALL),
            ), root_group)

        for priority, action_payload in enumerate(payload.get("actions", []) or []):
            MicrotechOrderRuleAction.objects.create(
                rule=rule,
                priority=priority,
                action_type=action_payload.get("action_type"),
                dataset_field_id=action_payload.get("dataset_field_id"),
                graphql_field=action_payload.get("graphql_field", "") or "",
                target_scope=(
                    action_payload.get("target_scope")
                    or MicrotechOrderRuleAction.TargetScope.CUSTOMER
                ),
                target_value=action_payload.get("target_value", ""),
            )

    return rule


__all__ = ["serialize_rule_for_edit", "save_rule_from_payload", "EditorValidationError"]
