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
