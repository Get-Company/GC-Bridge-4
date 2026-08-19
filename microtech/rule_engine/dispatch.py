from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from microtech.models import MicrotechOrderRule
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    action_type: str
    field_path: str
    value: str


def _first_matching_rule(*, task_name, phase, context):
    rules = (
        MicrotechOrderRule.objects
        .filter(is_active=True, engine_enabled=True, execution_phase=phase, trigger__task_name=task_name)
        .prefetch_related("condition_groups", "condition_groups__conditions",
                          "actions", "actions__dataset_field")
        .order_by("priority", "id")
    )
    for rule in rules:
        if rule_matches(rule, context):
            return rule
    return None


def _actions_for_rule(rule, context) -> list[ResolvedAction]:
    resolved = []
    for action in sorted((a for a in rule.actions.all() if a.is_active),
                         key=lambda i: (i.priority, i.id)):
        field_path = action.dataset_field.field_name if action.dataset_field_id else ""
        resolved.append(ResolvedAction(
            action_type=str(action.action_type),
            field_path=str(field_path),
            value=render_template(action.target_value or "", context),
        ))
    return resolved


def resolve_actions(*, task_name, phase, root_instance) -> list[ResolvedAction]:
    context = EvaluationContext(root_instance)
    rule = _first_matching_rule(task_name=task_name, phase=phase, context=context)
    if rule is None:
        return []
    return _actions_for_rule(rule, context)


def shadow_compare(*, task_name, phase, root_instance, legacy_result: dict) -> dict:
    engine_actions = {a.field_path: a.value for a in resolve_actions(
        task_name=task_name, phase=phase, root_instance=root_instance)}
    changed = {
        key: {"legacy": legacy_result.get(key), "engine": value}
        for key, value in engine_actions.items()
        if str(legacy_result.get(key, "")) != str(value)
    }
    diff = {"changed": changed, "engine": engine_actions, "legacy": legacy_result}
    if changed:
        logger.warning("Regelwerk Schatten-Diff für {} ({}): {}", task_name, phase, changed)
    else:
        logger.info("Regelwerk Schatten-Diff leer für {} ({}).", task_name, phase)
    return diff
