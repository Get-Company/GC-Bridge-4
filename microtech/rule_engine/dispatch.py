from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from microtech.models import MicrotechOrderRule, MicrotechSettings, RuleEngineShadowRun
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.order_resolver import ORDER_CREATE_TASK, resolve_order_rule
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


# --- Order-path mode facade ------------------------------------------------
#
# Single switch for the live order path. ``off`` keeps the legacy resolver
# authoritative (byte-identical to today); ``shadow`` runs the engine in
# parallel and persists diffs while the legacy result stays authoritative;
# ``live`` makes the engine authoritative (still logging diffs). Any engine
# error degrades gracefully to the legacy result so the order path never breaks.


def _legacy_resolve(order):
    from orders.services.order_rule_resolver import OrderRuleResolverService

    return OrderRuleResolverService().resolve_for_order(order=order)


def _actions_map(resolved) -> dict:
    out = {}
    for a in getattr(resolved, "dataset_actions", ()) or ():
        key = a.dataset_field_name or a.action_type
        out[key] = a.target_value
    return out


def _persist_shadow_run(order, legacy, engine) -> None:
    legacy_map, engine_map = _actions_map(legacy), _actions_map(engine)
    keys = set(legacy_map) | set(engine_map)
    changed = {
        key: {"legacy": legacy_map.get(key), "engine": engine_map.get(key)}
        for key in keys
        if str(legacy_map.get(key, "")) != str(engine_map.get(key, ""))
    }
    is_equal = not changed and (legacy.rule_id == engine.rule_id)
    try:
        RuleEngineShadowRun.objects.create(
            order_number=str(getattr(order, "order_number", "") or ""),
            task_name=ORDER_CREATE_TASK,
            engine_rule_id=engine.rule_id,
            legacy_rule_id=legacy.rule_id,
            is_equal=is_equal,
            changed_json=json.dumps(changed, ensure_ascii=False),
        )
    except Exception:
        logger.exception("Schatten-Lauf konnte nicht persistiert werden.")
    if not is_equal:
        logger.warning(
            "Regelwerk Schatten-Diff (order={}): rule legacy={} engine={} changed={}",
            getattr(order, "order_number", ""), legacy.rule_id, engine.rule_id, changed,
        )


def resolve_order_rule_with_mode(order):
    """Resolve the order rule honouring the configured engine mode."""
    try:
        mode = MicrotechSettings.load().rule_engine_order_mode
    except Exception:
        logger.exception("Regel-Engine-Modus nicht ladbar → 'off'.")
        mode = MicrotechSettings.EngineMode.OFF

    if mode == MicrotechSettings.EngineMode.OFF:
        return _legacy_resolve(order)

    legacy = _legacy_resolve(order)
    try:
        engine = resolve_order_rule(order)
    except Exception:
        logger.exception(
            "Regel-Engine-Auswertung fehlgeschlagen → Legacy maßgeblich (order={}).",
            getattr(order, "order_number", ""),
        )
        return legacy

    _persist_shadow_run(order, legacy, engine)
    if mode == MicrotechSettings.EngineMode.LIVE:
        return engine
    return legacy
