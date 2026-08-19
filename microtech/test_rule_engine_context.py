from django.test import TestCase
from microtech.rule_engine.context import EvaluationContext


class _Addr:
    country_code = "CH"


class _Order:
    total = 750
    billing_address = _Addr()


class ContextTest(TestCase):
    def test_resolves_nested_path(self):
        ctx = EvaluationContext(_Order())
        self.assertEqual(ctx.get("total"), 750)
        self.assertEqual(ctx.get("billing_address__country_code"), "CH")

    def test_missing_segment_returns_none(self):
        ctx = EvaluationContext(_Order())
        self.assertIsNone(ctx.get("billing_address__missing"))
        self.assertIsNone(ctx.get("nope"))
