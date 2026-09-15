"""Tests for rule-engine activation / order-path cutover (Plan 2026-09-15)."""
from __future__ import annotations

import pytest

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    RuleTrigger,
)
from orders.models import Order
from orders.services.order_rule_resolver import ResolvedOrderRule

pytestmark = pytest.mark.django_db

ORDER_CREATE_TASK = "orders.microtech_order_upsert"


def _order_trigger():
    return RuleTrigger.objects.get_or_create(
        code="order_create",
        defaults=dict(
            label="Bestellung anlegen",
            task_name=ORDER_CREATE_TASK,
            context_root="orders.Order",
            is_active=True,
            priority=10,
        ),
    )[0]


_ORDER_SEQ = {"n": 0}


def _make_order(**kw):
    _ORDER_SEQ["n"] += 1
    n = _ORDER_SEQ["n"]
    return Order.objects.create(
        order_number=kw.pop("order_number", f"A{n}"),
        api_id=kw.pop("api_id", f"api{n}"),
        **kw,
    )


def _catalog(field_name="ZahlArt", field_type="Integer"):
    _ORDER_SEQ["n"] += 1
    n = _ORDER_SEQ["n"]
    cat = MicrotechDatasetCatalog.objects.create(
        code=f"vorgang{n}", name="Vorgang", source_identifier=f"Vorgang - Vorgange {n}",
    )
    fld = MicrotechDatasetField.objects.create(
        dataset=cat, field_name=field_name, field_type=field_type,
    )
    return cat, fld


# --- Task 1: engine order resolver ---------------------------------------


def test_engine_builds_set_field_dataset_action():
    from microtech.rule_engine.order_resolver import resolve_order_rule

    trg = _order_trigger()
    cat, fld = _catalog("ZahlArt", "Integer")
    rule = MicrotechOrderRule.objects.create(
        name="Engine ZahlArt", is_active=True, engine_enabled=True, trigger=trg,
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=5,
    )
    MicrotechOrderRuleAction.objects.create(
        rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
        dataset=cat, dataset_field=fld, target_value="22", is_active=True,
    )
    order = _make_order()

    resolved = resolve_order_rule(order)

    assert isinstance(resolved, ResolvedOrderRule)
    assert resolved.rule_id == rule.pk
    assert len(resolved.dataset_actions) == 1
    a = resolved.dataset_actions[0]
    assert a.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD
    assert a.dataset_field_name == "ZahlArt"
    assert a.dataset_field_type == "Integer"
    assert a.target_value == "22"


def test_engine_no_match_returns_defaults_with_customer_type():
    from microtech.rule_engine.order_resolver import resolve_order_rule

    order = _make_order()
    resolved = resolve_order_rule(order)
    assert resolved.dataset_actions == ()
    assert resolved.rule_id is None
    assert resolved.customer_type in (
        MicrotechOrderRule.CustomerType.PRIVATE,
        MicrotechOrderRule.CustomerType.COMPANY,
    )


def test_engine_ignores_rules_without_engine_enabled():
    from microtech.rule_engine.order_resolver import resolve_order_rule

    trg = _order_trigger()
    MicrotechOrderRule.objects.create(
        name="Nicht aktiviert", is_active=True, engine_enabled=False, trigger=trg,
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=1,
    )
    resolved = resolve_order_rule(_make_order())
    assert resolved.rule_id is None


# --- Task 2: shared customer-type heuristic ------------------------------


def test_shared_detect_customer_type_matches_service():
    from orders.services.order_rule_resolver import (
        OrderRuleResolverService,
        detect_customer_type,
    )

    order = _make_order()
    shared = detect_customer_type(order=order)
    service = OrderRuleResolverService()._detect_customer_type(order=order)
    assert shared == service


# --- Task 3: mode setting + shadow-run model -----------------------------


def test_engine_mode_default_off_and_choices():
    from microtech.models import MicrotechSettings

    s = MicrotechSettings.load()
    assert s.rule_engine_order_mode == MicrotechSettings.EngineMode.OFF
    values = {c[0] for c in MicrotechSettings.EngineMode.choices}
    assert values == {"off", "shadow", "live"}


def test_shadow_run_model_orders_newest_first():
    from microtech.models import RuleEngineShadowRun

    RuleEngineShadowRun.objects.create(order_number="X1", task_name="t", is_equal=True, changed_json="{}")
    RuleEngineShadowRun.objects.create(order_number="X2", task_name="t", is_equal=False, changed_json="{}")
    newest = list(RuleEngineShadowRun.objects.values_list("order_number", flat=True))[:2]
    assert newest == ["X2", "X1"]


# --- Task 4: mode facade -------------------------------------------------


def test_mode_off_returns_legacy_no_log(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch

    s = MicrotechSettings.load()
    s.rule_engine_order_mode = MicrotechSettings.EngineMode.OFF
    s.save()
    order = _make_order()
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(rule_id=99, rule_name="legacy"))

    def _boom(o):
        raise AssertionError("engine must not run in off mode")

    monkeypatch.setattr(dispatch, "resolve_order_rule", _boom)
    result = dispatch.resolve_order_rule_with_mode(order)
    assert result.rule_id == 99
    assert RuleEngineShadowRun.objects.count() == 0


def test_mode_shadow_logs_and_returns_legacy(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch
    from orders.services.order_rule_resolver import ResolvedDatasetAction

    s = MicrotechSettings.load()
    s.rule_engine_order_mode = MicrotechSettings.EngineMode.SHADOW
    s.save()
    order = _make_order()
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(
        rule_id=1,
        dataset_actions=(ResolvedDatasetAction(action_type="set_field", dataset_field_name="ZahlArt", target_value="10"),),
    ))
    monkeypatch.setattr(dispatch, "resolve_order_rule", lambda o: ResolvedOrderRule(
        rule_id=2,
        dataset_actions=(ResolvedDatasetAction(action_type="set_field", dataset_field_name="ZahlArt", target_value="22"),),
    ))
    result = dispatch.resolve_order_rule_with_mode(order)
    assert result.rule_id == 1  # Legacy maßgeblich
    run = RuleEngineShadowRun.objects.latest("created_at")
    assert run.is_equal is False
    assert '"ZahlArt"' in run.changed_json


def test_mode_live_returns_engine(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch

    s = MicrotechSettings.load()
    s.rule_engine_order_mode = MicrotechSettings.EngineMode.LIVE
    s.save()
    order = _make_order()
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(rule_id=1))
    monkeypatch.setattr(dispatch, "resolve_order_rule", lambda o: ResolvedOrderRule(rule_id=2))
    assert dispatch.resolve_order_rule_with_mode(order).rule_id == 2


def test_mode_live_engine_error_falls_back_to_legacy(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch

    s = MicrotechSettings.load()
    s.rule_engine_order_mode = MicrotechSettings.EngineMode.LIVE
    s.save()
    order = _make_order()
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(rule_id=1, rule_name="legacy"))

    def _boom(o):
        raise RuntimeError("engine down")

    monkeypatch.setattr(dispatch, "resolve_order_rule", _boom)
    assert dispatch.resolve_order_rule_with_mode(order).rule_id == 1
