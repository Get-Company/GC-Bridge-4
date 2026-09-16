from __future__ import annotations

import json
from loguru import logger

from microtech.models import MicrotechSettings, RuleEngineShadowRun
from microtech.rule_engine.execution import ResolvedRuleAction as ResolvedAction, RuleExecutionService
from microtech.rule_engine.order_resolver import ORDER_CREATE_TASK, resolve_order_rule


def resolve_actions(*, task_name, phase, root_instance) -> list[ResolvedAction]:
    match = RuleExecutionService().resolve_first_match(
        task_name=task_name,
        phase=phase,
        root_instance=root_instance,
    )
    if match is None:
        return []
    return list(match.actions)


def shadow_compare(*, task_name, phase, root_instance, legacy_result: dict) -> dict:
    engine_actions = _action_values_by_target(resolve_actions(
        task_name=task_name, phase=phase, root_instance=root_instance))
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


def _action_values_by_target(actions) -> dict[str, str]:
    """Keep repeated targets visible instead of overwriting them in a dict."""
    values: dict[str, str] = {}
    seen: dict[str, int] = {}
    for action in actions:
        base = str(action.field_path or action.action_type or "action")
        sequence = seen.get(base, 0) + 1
        seen[base] = sequence
        key = base if sequence == 1 else f"{base}#{sequence}"
        values[key] = action.value
    return values


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
    seen: dict[str, int] = {}
    for a in getattr(resolved, "dataset_actions", ()) or ():
        key_base = ":".join((
            str(a.action_type or ""),
            str(a.dataset_source_identifier or ""),
            str(a.dataset_field_name or ""),
        ))
        sequence = seen.get(key_base, 0) + 1
        seen[key_base] = sequence
        key = key_base if sequence == 1 else f"{key_base}#{sequence}"
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


# --- Address-path input overlay (generic) ---------------------------------
#
# Returns a {graphql_field: value} overlay for the GraphQL postal-address input.
# In live mode it returns the engine's fields (any PostalAddressInput field at
# once); in off/shadow it returns {} so the hardcoded input stays authoritative.


def _persist_address_shadow_run(address, changed) -> None:
    from microtech.rule_engine.address_resolver import ADDRESS_WRITE_TASK

    try:
        RuleEngineShadowRun.objects.create(
            order_number=str(getattr(address, "pk", "") or ""),
            task_name=ADDRESS_WRITE_TASK,
            engine_rule_id=None,
            legacy_rule_id=None,
            is_equal=not changed,
            changed_json=json.dumps(changed, ensure_ascii=False),
        )
    except Exception:
        logger.exception("Anschrift-Schatten-Lauf konnte nicht persistiert werden.")
    if changed:
        logger.warning("Anschrift-Feld Schatten-Diff (address={}): {}", getattr(address, "pk", ""), changed)


def resolve_postal_address_with_mode(address, *, code_values) -> dict:
    """Overlay for the GraphQL postal-address input, honouring rule_engine_address_mode."""
    try:
        mode = MicrotechSettings.load().rule_engine_address_mode
    except Exception:
        logger.exception("Adress-Engine-Modus nicht ladbar → 'off'.")
        mode = MicrotechSettings.EngineMode.OFF

    if mode == MicrotechSettings.EngineMode.OFF:
        return {}

    try:
        from microtech.rule_engine.address_resolver import resolve_address_fields

        engine = resolve_address_fields(address)
    except Exception:
        logger.exception("Anschrift-Engine-Auswertung fehlgeschlagen → Code-Fallback (address={}).",
                         getattr(address, "pk", ""))
        return {}

    changed = {
        key: {"code": (code_values or {}).get(key), "engine": value}
        for key, value in engine.items()
        if str((code_values or {}).get(key, "")) != str(value)
    }
    _persist_address_shadow_run(address, changed)
    if mode == MicrotechSettings.EngineMode.LIVE:
        return engine
    return {}


# --- Customer-path input overlay (generic) --------------------------------
#
# Returns a {graphql_field: value} overlay for the GraphQL customer input.
# In live mode it returns the engine's fields (any CustomerInput field at once);
# in off/shadow it returns {} so the hardcoded input stays authoritative.


def _persist_customer_shadow_run(customer, changed) -> None:
    from microtech.rule_engine.customer_resolver import CUSTOMER_WRITE_TASK

    try:
        RuleEngineShadowRun.objects.create(
            order_number=str(getattr(customer, "pk", "") or ""),
            task_name=CUSTOMER_WRITE_TASK,
            engine_rule_id=None,
            legacy_rule_id=None,
            is_equal=not changed,
            changed_json=json.dumps(changed, ensure_ascii=False),
        )
    except Exception:
        logger.exception("Kunden-Schatten-Lauf konnte nicht persistiert werden.")
    if changed:
        logger.warning("Kunden-Feld Schatten-Diff (customer={}): {}", getattr(customer, "pk", ""), changed)


def resolve_customer_input_with_mode(*, customer, address, billing_address=None, code_values) -> dict:
    """Overlay for the GraphQL customer input, honouring rule_engine_customer_mode."""
    try:
        mode = MicrotechSettings.load().rule_engine_customer_mode
    except Exception:
        logger.exception("Kunden-Engine-Modus nicht ladbar → 'off'.")
        mode = MicrotechSettings.EngineMode.OFF

    if mode == MicrotechSettings.EngineMode.OFF:
        return {}

    try:
        from microtech.rule_engine.customer_resolver import resolve_customer_fields

        engine = resolve_customer_fields(customer=customer, address=address, billing_address=billing_address)
    except Exception:
        logger.exception("Kunden-Engine-Auswertung fehlgeschlagen → Code-Fallback (customer={}).",
                         getattr(customer, "pk", ""))
        return {}

    changed = {
        key: {"code": (code_values or {}).get(key), "engine": value}
        for key, value in engine.items()
        if str((code_values or {}).get(key, "")) != str(value)
    }
    _persist_customer_shadow_run(customer, changed)
    if mode == MicrotechSettings.EngineMode.LIVE:
        return engine
    return {}
