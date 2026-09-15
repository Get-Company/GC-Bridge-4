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
