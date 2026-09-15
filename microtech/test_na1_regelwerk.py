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
