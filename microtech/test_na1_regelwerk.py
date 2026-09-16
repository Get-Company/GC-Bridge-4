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


# --- Address-path generic overlay facade ---------------------------------


class _FakeAddr:
    pk = 1


def _set_address_mode(mode):
    from microtech.models import MicrotechSettings

    s = MicrotechSettings.load()
    s.rule_engine_address_mode = mode
    s.save()


def test_address_facade_off_returns_empty_no_engine(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.OFF)

    def _boom(a):
        raise AssertionError("engine must not run in off mode")

    monkeypatch.setattr(address_resolver, "resolve_address_fields", _boom)
    assert dispatch.resolve_postal_address_with_mode(_FakeAddr(), code_values={}) == {}
    assert RuleEngineShadowRun.objects.filter(task_name=address_resolver.ADDRESS_WRITE_TASK).count() == 0


def test_address_facade_shadow_logs_and_returns_empty(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.SHADOW)
    monkeypatch.setattr(address_resolver, "resolve_address_fields", lambda a: {"name1": "Firma", "name3": "D"})
    result = dispatch.resolve_postal_address_with_mode(_FakeAddr(), code_values={"name1": "Herr", "name3": ""})
    assert result == {}  # shadow keeps code
    run = RuleEngineShadowRun.objects.filter(task_name=address_resolver.ADDRESS_WRITE_TASK).latest("created_at")
    assert run.is_equal is False and "name1" in run.changed_json and "name3" in run.changed_json


def test_address_facade_live_returns_engine_dict(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.LIVE)
    monkeypatch.setattr(address_resolver, "resolve_address_fields", lambda a: {"name1": "Firma", "name3": "D"})
    assert dispatch.resolve_postal_address_with_mode(_FakeAddr(), code_values={}) == {"name1": "Firma", "name3": "D"}


def test_address_facade_engine_error_returns_empty(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch, address_resolver

    _set_address_mode(MicrotechSettings.EngineMode.LIVE)

    def _boom(a):
        raise RuntimeError("engine down")

    monkeypatch.setattr(address_resolver, "resolve_address_fields", _boom)
    assert dispatch.resolve_postal_address_with_mode(_FakeAddr(), code_values={}) == {}


def test_build_postal_address_input_overlays_any_field(monkeypatch):
    from customer.models import Customer, Address
    from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
    from microtech.rule_engine import dispatch

    cust = Customer.objects.create()
    addr = Address.objects.create(customer=cust, title="mr", name1="Max Mustermann",
                                  first_name="Max", last_name="Mustermann", name3="")
    svc = CustomerUpsertMicrotechService()

    # live overlay covers arbitrary fields (name1 AND name3) at once
    monkeypatch.setattr(dispatch, "resolve_postal_address_with_mode",
                        lambda a, *, code_values: {"name1": "ENGINE", "name3": "D"})
    out = svc._build_postal_address_input(
        address=addr, is_shipping=True, is_invoice=False, na1_mode="auto", na1_static_value="")
    assert out["name1"] == "ENGINE" and out["name3"] == "D"

    # empty overlay (off/shadow/error) → hardcoded code value (auto → "Herr")
    monkeypatch.setattr(dispatch, "resolve_postal_address_with_mode",
                        lambda a, *, code_values: {})
    out2 = svc._build_postal_address_input(
        address=addr, is_shipping=True, is_invoice=False, na1_mode="auto", na1_static_value="")
    assert out2["name1"] == "Herr"


# --- Task 8: editor meta carries context_root + address fields -----------


def test_meta_view_includes_address_fields_with_context_root(admin_client):
    import json
    from django.urls import reverse

    url = reverse("admin:microtech_orderrule_builder_meta")
    data = json.loads(admin_client.get(url).content)
    # name1 exists for the address context (also emitted for the customer context)
    addr_name1 = next(
        f for f in data["django_fields"]
        if f["path"] == "name1" and f["context_root"] == "customer.Address"
    )
    assert "not_in_list" in addr_name1["allowed_operator_codes"]
    order_country = next(
        f for f in data["django_fields"]
        if f["path"] == "billing_address__country_code"
    )
    assert order_country["context_root"] == "orders.Order"
    # trigger context roots available for the JS filter
    roots = {t["context_root"] for t in data["triggers"]}
    assert "customer.Address" in roots


def test_dataset_fields_grouped_endpoint(admin_client):
    import json
    from django.urls import reverse
    from microtech.models import MicrotechDatasetCatalog, MicrotechDatasetField

    cat = MicrotechDatasetCatalog.objects.create(
        code="adressen", name="Adressen", source_identifier="Adressen - Adressen", priority=10)
    MicrotechDatasetField.objects.create(dataset=cat, field_name="UStKat", label="Steuerkategorie", priority=1)
    MicrotechDatasetField.objects.create(dataset=cat, field_name="Na3", label="Name 3", priority=2)

    url = reverse("admin:microtech_orderrule_dataset_fields_grouped")
    data = json.loads(admin_client.get(url).content)
    assert data["ok"] is True
    adressen = next(d for d in data["datasets"] if d["name"] == "Adressen")
    field_names = [f["field_name"] for f in adressen["fields"]]
    assert field_names == ["UStKat", "Na3"]  # by priority
    assert adressen["fields"][0]["label"] == "Steuerkategorie"


# --- GraphQL schema catalog ----------------------------------------------


def test_introspection_parses_input_objects(monkeypatch):
    from microtech import graphql_schema
    from microtech.services.graphql_client import MicrotechGraphQLClientService

    schema = {"__schema": {"types": [
        {"kind": "INPUT_OBJECT", "name": "CustomerInput",
         "inputFields": [{"name": "taxCategory"}, {"name": "name1"}]},
        {"kind": "OBJECT", "name": "Customer", "inputFields": None},
        {"kind": "INPUT_OBJECT", "name": "PostalAddressInput",
         "inputFields": [{"name": "name1"}, {"name": "country"}]},
    ]}}
    monkeypatch.setattr(MicrotechGraphQLClientService, "execute", lambda self, *a, **k: schema)
    raw = graphql_schema.introspect_input_fields()
    assert raw["CustomerInput"] == ["taxCategory", "name1"]
    assert raw["PostalAddressInput"] == ["name1", "country"]
    assert "Customer" not in raw  # non-input object skipped


def test_catalog_falls_back_when_introspection_fails(monkeypatch):
    from django.core.cache import cache
    from microtech import graphql_schema

    cache.clear()
    monkeypatch.setattr(graphql_schema, "introspect_input_fields",
                        lambda: (_ for _ in ()).throw(RuntimeError("wrapper down")))
    catalog = graphql_schema.get_graphql_input_catalog(refresh=True)
    assert catalog["source"] == "fallback"
    types = {g["input_type"] for g in catalog["groups"]}
    assert "CustomerInput" in types and "PostalAddressInput" in types


def test_graphql_fields_endpoint(admin_client, monkeypatch):
    import json
    from django.core.cache import cache
    from django.urls import reverse
    from microtech import graphql_schema

    cache.clear()
    monkeypatch.setattr(graphql_schema, "introspect_input_fields",
                        lambda: {"CustomerInput": ["taxCategory"]})
    url = reverse("admin:microtech_orderrule_graphql_fields_grouped") + "?refresh=1"
    data = json.loads(admin_client.get(url).content)
    assert data["ok"] is True
    cust = next(g for g in data["groups"] if g["input_type"] == "CustomerInput")
    assert cust["fields"][0]["name"] == "taxCategory"


def test_resolve_address_fields_keys_on_graphql_field():
    from customer.models import Customer, Address
    from microtech.models import (
        MicrotechOrderRule, MicrotechOrderRuleAction, RuleTrigger,
    )
    from microtech.rule_engine.address_resolver import resolve_address_fields

    trg = RuleTrigger.objects.get(code="address_write")
    rule = MicrotechOrderRule.objects.create(
        name="GraphQL Na1", is_active=True, engine_enabled=True, trigger=trg,
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=5)
    MicrotechOrderRuleAction.objects.create(
        rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
        graphql_field="PostalAddressInput.name1", target_value="Firma")
    cust = Customer.objects.create()
    addr = Address.objects.create(customer=cust, name1="ACME GmbH")
    assert resolve_address_fields(addr) == {"name1": "Firma"}


def test_action_graphql_field_round_trip():
    from microtech.models import MicrotechOrderRule, RuleTrigger
    from microtech.rule_engine.editor import save_rule_from_payload, serialize_rule_for_edit

    trg = RuleTrigger.objects.get(code="address_write")
    payload = {
        "name": "RT", "priority": 10, "is_active": True, "execution_phase": "before",
        "engine_enabled": True, "shadow_mode": True, "trigger_id": trg.id,
        "root_group": None,
        "actions": [{"action_type": "set_field", "graphql_field": "CustomerInput.taxCategory",
                     "dataset_field_id": None, "target_value": "2"}],
    }
    rule = save_rule_from_payload(payload)
    data = serialize_rule_for_edit(MicrotechOrderRule.objects.get(pk=rule.pk))
    assert data["actions"][0]["graphql_field"] == "CustomerInput.taxCategory"


# --- Customer path (taxCategory) wiring ----------------------------------


def _customer_tax_rule(country="DE", tax_value="99"):
    from microtech.models import (
        MicrotechOrderRule, MicrotechOrderRuleAction,
        MicrotechOrderRuleCondition, MicrotechOrderRuleConditionGroup, RuleTrigger,
    )

    trg = RuleTrigger.objects.get(code="customer_create")
    rule = MicrotechOrderRule.objects.create(
        name=f"{country}->{tax_value}", is_active=True, engine_enabled=True, trigger=trg,
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=10)
    g = MicrotechOrderRuleConditionGroup.objects.create(rule=rule, parent=None, logic="all")
    MicrotechOrderRuleCondition.objects.create(
        rule=rule, group=g, django_field_path="country_code", operator_code="eq", expected_value=country)
    MicrotechOrderRuleAction.objects.create(
        rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
        graphql_field="CustomerInput.taxCategory", target_value=tax_value)
    return rule


def test_resolve_customer_fields_by_billing_country():
    from customer.models import Customer, Address
    from microtech.rule_engine.customer_resolver import resolve_customer_fields

    _customer_tax_rule(country="DE", tax_value="1")
    cust = Customer.objects.create()
    de = Address.objects.create(customer=cust, country_code="DE")
    ch = Address.objects.create(customer=cust, country_code="CH")
    assert resolve_customer_fields(customer=cust, address=de) == {"taxCategory": "1"}
    # non-matching billing country, no fallback rule → no override
    assert resolve_customer_fields(customer=cust, address=ch) == {}
    # billing_address wins over address for the tax country
    assert resolve_customer_fields(customer=cust, address=ch, billing_address=de) == {"taxCategory": "1"}


def test_build_customer_input_overlays_only_in_live(monkeypatch):
    from customer.models import Customer, Address
    from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
    from microtech.models import MicrotechSettings

    _customer_tax_rule(country="DE", tax_value="99")
    cust = Customer.objects.create()
    addr = Address.objects.create(customer=cust, country_code="DE", name1="ACME")
    svc = CustomerUpsertMicrotechService()

    s = MicrotechSettings.load(); s.rule_engine_customer_mode = MicrotechSettings.EngineMode.LIVE; s.save()
    live = svc._build_customer_input(customer=cust, address=addr, billing_address=addr)
    assert live["taxCategory"] == "99"  # engine overlay wins

    s.rule_engine_customer_mode = MicrotechSettings.EngineMode.OFF; s.save()
    off = svc._build_customer_input(customer=cust, address=addr, billing_address=addr)
    assert off["taxCategory"] != "99"  # hardcoded resolve_tax_category value


def test_meta_customer_context_has_address_fields(admin_client):
    import json
    from django.urls import reverse

    url = reverse("admin:microtech_orderrule_builder_meta")
    data = json.loads(admin_client.get(url).content)
    customer_ctx = [f for f in data["django_fields"] if f["context_root"] == "customer.Customer"]
    paths = {f["path"] for f in customer_ctx}
    assert "country_code" in paths
