"""Tests for the Na1 rule engine (Plan 2026-09-15-na1-regelwerk)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


# --- Task 1: list operators ----------------------------------------------


def test_in_list_and_not_in_list_operators():
    from microtech.rule_engine.operators import evaluate_operator

    assert evaluate_operator("in_list", "herr", "herr,frau", "", "string") is True
    assert evaluate_operator("not_in_list", "ACME GmbH", "herr,frau", "", "string") is True
    # case-insensitive + newline separator
    assert evaluate_operator("in_list", "HERR", "herr\nfrau", "", "string") is True
    # empty actual is never "in list"
    assert evaluate_operator("in_list", "", "a,b", "", "string") is False
    assert evaluate_operator("not_in_list", "", "a,b", "", "string") is True


def test_parse_list_trims_and_drops_empty():
    from microtech.rule_engine.operators import parse_list

    assert parse_list(" herr , frau ,\n mr \n") == ["herr", "frau", "mr"]
    assert parse_list("") == []


# --- Task 2: anrede constant + resolvers ---------------------------------


def test_anreden_resolver_returns_seeded_salutations():
    from microtech.rule_engine.context import EvaluationContext
    from microtech.rule_engine.resolvers import resolve_named

    ctx = EvaluationContext(object())
    result = resolve_named("anreden", ctx)
    tokens = {t.strip() for t in result.split(",")}
    assert "herr" in tokens and "frau" in tokens and "mr" in tokens


def test_anrede_resolver_from_address_context():
    from customer.models import Customer, Address
    from microtech.rule_engine.context import EvaluationContext
    from microtech.rule_engine.resolvers import resolve_named

    cust = Customer.objects.create()
    addr = Address.objects.create(customer=cust, title="mr", name1="Max Mustermann")
    ctx = EvaluationContext(addr)
    assert resolve_named("anrede", ctx) == "Herr"

    addr2 = Address.objects.create(customer=cust, title="", name1="Frau")
    ctx2 = EvaluationContext(addr2)
    assert resolve_named("anrede", ctx2) == "Frau"


# --- Task 3: address trigger + context-aware field catalog ----------------


def test_address_field_defs_expose_address_fields():
    from microtech.rule_builder import get_address_field_defs

    paths = {d.path for d in get_address_field_defs()}
    assert {"name1", "title", "first_name", "last_name"} <= paths
    assert all(d.context_root == "customer.Address" for d in get_address_field_defs())


def test_order_catalog_unchanged_and_trigger_seeded():
    from microtech.rule_builder import get_django_field_map, get_operator_engine_map
    from microtech.models import RuleTrigger

    assert "billing_address__country_code" in get_django_field_map()
    engine_map = get_operator_engine_map()
    assert engine_map.get("in_list") == "in_list"
    assert engine_map.get("not_in_list") == "not_in_list"
    assert RuleTrigger.objects.filter(code="address_write", is_active=True).exists()


# --- Task 4: address engine mode setting ---------------------------------


def test_address_mode_default_off():
    from microtech.models import MicrotechSettings

    assert MicrotechSettings.load().rule_engine_address_mode == MicrotechSettings.EngineMode.OFF


# --- Task 5: resolve_address_fields --------------------------------------


def _na1_field():
    from microtech.models import MicrotechDatasetCatalog, MicrotechDatasetField

    cat, _ = MicrotechDatasetCatalog.objects.get_or_create(
        code="adressen", defaults=dict(name="Adressen", source_identifier="Adressen - Adressen"))
    fld, _ = MicrotechDatasetField.objects.get_or_create(dataset=cat, field_name="Na1", defaults=dict(field_type="String"))
    return fld


def _address_trigger():
    from microtech.models import RuleTrigger

    return RuleTrigger.objects.get(code="address_write")


def _company_rule():
    """Rule: company detection conditions → Na1 = 'Firma'."""
    from microtech.models import (
        MicrotechOrderRule, MicrotechOrderRuleAction,
        MicrotechOrderRuleCondition, MicrotechOrderRuleConditionGroup,
    )

    rule = MicrotechOrderRule.objects.create(
        name="Firma → Na1", is_active=True, engine_enabled=True, trigger=_address_trigger(),
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=10)
    g = MicrotechOrderRuleConditionGroup.objects.create(rule=rule, parent=None, logic="all")
    conds = [
        ("name1", "is_not_empty", ""),
        ("name1", "not_in_list", "{{ @anreden }}"),
        ("name1", "ne", "{{ title }}"),
        ("name1", "ne", "{{ first_name }} {{ last_name }}"),
    ]
    for path, op, expected in conds:
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=g, django_field_path=path, operator_code=op, expected_value=expected)
    MicrotechOrderRuleAction.objects.create(
        rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
        dataset_field=_na1_field(), target_value="Firma")
    return rule


def _private_fallback_rule():
    """Fallback rule (no conditions) → Na1 = {{ @anrede }}."""
    from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction

    rule = MicrotechOrderRule.objects.create(
        name="Privat → Na1", is_active=True, engine_enabled=True, trigger=_address_trigger(),
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=100)
    MicrotechOrderRuleAction.objects.create(
        rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
        dataset_field=_na1_field(), target_value="{{ @anrede }}")
    return rule


def test_resolve_address_fields_company_and_private():
    from customer.models import Customer, Address
    from microtech.rule_engine.address_resolver import resolve_address_fields

    _company_rule()
    _private_fallback_rule()
    cust = Customer.objects.create()

    company = Address.objects.create(customer=cust, name1="ACME GmbH", title="", first_name="", last_name="")
    assert resolve_address_fields(company) == {"Na1": "Firma"}

    private = Address.objects.create(
        customer=cust, name1="Max Mustermann", title="mr", first_name="Max", last_name="Mustermann")
    assert resolve_address_fields(private) == {"Na1": "Herr"}


def test_resolve_address_fields_no_rule_returns_empty():
    from customer.models import Customer, Address
    from microtech.rule_engine.address_resolver import resolve_address_fields

    cust = Customer.objects.create()
    addr = Address.objects.create(customer=cust, name1="ACME GmbH")
    assert resolve_address_fields(addr) == {}


# --- Task 6: resolve_address_na1_with_mode facade ------------------------


class _FakeAddr:
    pk = 1


def _set_address_mode(mode):
    from microtech.models import MicrotechSettings

    s = MicrotechSettings.load()
    s.rule_engine_address_mode = mode
    s.save()


def test_na1_facade_off_returns_none_no_engine(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.OFF)

    def _boom(a):
        raise AssertionError("engine must not run in off mode")

    monkeypatch.setattr(address_resolver, "resolve_address_fields", _boom)
    monkeypatch.setattr(dispatch, "_code_na1", _boom)
    assert dispatch.resolve_address_na1_with_mode(_FakeAddr()) is None
    assert RuleEngineShadowRun.objects.filter(task_name=address_resolver.ADDRESS_WRITE_TASK).count() == 0


def test_na1_facade_shadow_logs_and_returns_none(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.SHADOW)
    monkeypatch.setattr(address_resolver, "resolve_address_fields", lambda a: {"Na1": "Firma"})
    monkeypatch.setattr(dispatch, "_code_na1", lambda a: "Herr")
    assert dispatch.resolve_address_na1_with_mode(_FakeAddr()) is None
    run = RuleEngineShadowRun.objects.filter(task_name=address_resolver.ADDRESS_WRITE_TASK).latest("created_at")
    assert run.is_equal is False and "Na1" in run.changed_json


def test_na1_facade_live_returns_engine(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.LIVE)
    monkeypatch.setattr(address_resolver, "resolve_address_fields", lambda a: {"Na1": "Firma"})
    monkeypatch.setattr(dispatch, "_code_na1", lambda a: "Herr")
    assert dispatch.resolve_address_na1_with_mode(_FakeAddr()) == "Firma"


def test_na1_facade_engine_error_returns_none(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.LIVE)

    def _boom(a):
        raise RuntimeError("engine down")

    monkeypatch.setattr(address_resolver, "resolve_address_fields", _boom)
    assert dispatch.resolve_address_na1_with_mode(_FakeAddr()) is None


# --- Task 7: wiring in _build_postal_address_input -----------------------


def test_postal_address_input_uses_engine_na1_or_code(monkeypatch):
    from customer.models import Customer, Address
    from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
    from microtech.rule_engine import dispatch

    cust = Customer.objects.create()
    addr = Address.objects.create(customer=cust, title="mr", name1="Max Mustermann",
                                  first_name="Max", last_name="Mustermann")
    svc = CustomerUpsertMicrotechService()

    # Engine liefert Wert (live-Erfolg) → wird übernommen
    monkeypatch.setattr(dispatch, "resolve_address_na1_with_mode", lambda a: "ENGINE")
    out = svc._build_postal_address_input(
        address=addr, is_shipping=True, is_invoice=False, na1_mode="auto", na1_static_value="")
    assert out["name1"] == "ENGINE"

    # Engine None (off/shadow/Fehler) → Code-Wert (auto → Anrede "Herr")
    monkeypatch.setattr(dispatch, "resolve_address_na1_with_mode", lambda a: None)
    out2 = svc._build_postal_address_input(
        address=addr, is_shipping=True, is_invoice=False, na1_mode="auto", na1_static_value="")
    assert out2["name1"] == "Herr"


# --- Task 8: editor meta carries context_root + address fields -----------


def test_meta_view_includes_address_fields_with_context_root(admin_client):
    import json
    from django.urls import reverse

    url = reverse("admin:microtech_orderrule_builder_meta")
    data = json.loads(admin_client.get(url).content)
    by_path = {f["path"]: f for f in data["django_fields"]}
    assert by_path["name1"]["context_root"] == "customer.Address"
    assert "not_in_list" in by_path["name1"]["allowed_operator_codes"]
    assert by_path["billing_address__country_code"]["context_root"] == "orders.Order"
    # trigger context roots available for the JS filter
    roots = {t["context_root"] for t in data["triggers"]}
    assert "customer.Address" in roots
