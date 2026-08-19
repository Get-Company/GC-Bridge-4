from django.test import TestCase

from microtech.rule_engine.operators import evaluate_operator


class EngineOperatorSeedTest(TestCase):
    def test_new_operators_present_in_enum(self):
        from microtech.models import MicrotechOrderRuleOperator as Op
        codes = {c for c, _ in Op.EngineOperator.choices}
        self.assertTrue({"between", "before", "after", "is_true", "is_false"} <= codes)


class OperatorHandlerTest(TestCase):
    def test_between_decimal_inclusive(self):
        self.assertTrue(evaluate_operator("between", "750", "500", "9999", "decimal"))
        self.assertFalse(evaluate_operator("between", "12000", "500", "9999", "decimal"))

    def test_before_after_date(self):
        self.assertTrue(evaluate_operator("before", "2026-01-01", "2026-06-01", "", "date"))
        self.assertTrue(evaluate_operator("after", "2026-12-01", "2026-06-01", "", "date"))

    def test_is_true_is_false(self):
        self.assertTrue(evaluate_operator("is_true", "ja", "", "", "bool"))
        self.assertTrue(evaluate_operator("is_false", "nein", "", "", "bool"))

    def test_eq_delegates_like_legacy(self):
        self.assertTrue(evaluate_operator("eq", "CH", "ch", "", "string"))
