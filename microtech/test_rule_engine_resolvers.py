# microtech/test_rule_engine_resolvers.py
from django.test import TestCase
from microtech.models import RuleConstant
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.resolvers import resolve_named


class _Order:
    def __init__(self, country, vat, group):
        self.billing_country_code = country
        self.vat_id = vat
        self.customer_group = group


class ResolverTest(TestCase):
    def setUp(self):
        # Migration 0033 already seeds these RuleConstant rows; update in place
        # instead of create() to avoid a duplicate-key IntegrityError.
        RuleConstant.objects.update_or_create(
            key="eu_country_codes", defaults={"value": "DE,IT,FR", "kind": "list"}
        )
        RuleConstant.objects.update_or_create(
            key="italian_b2b_group", defaults={"value": "italien-b2b", "kind": "scalar"}
        )

    def test_steuerkategorie_domestic_is_1(self):
        ctx = EvaluationContext(_Order("DE", "", ""))
        self.assertEqual(resolve_named("steuerkategorie", ctx), "1")

    def test_steuerkategorie_swiss_is_2(self):
        ctx = EvaluationContext(_Order("CH", "", ""))
        self.assertEqual(resolve_named("steuerkategorie", ctx), "2")

    def test_unknown_resolver_raises(self):
        with self.assertRaises(KeyError):
            resolve_named("nope", EvaluationContext(_Order("DE", "", "")))
