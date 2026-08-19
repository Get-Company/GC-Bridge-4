from django.test import TestCase


class EngineOperatorSeedTest(TestCase):
    def test_new_operators_present_in_enum(self):
        from microtech.models import MicrotechOrderRuleOperator as Op
        codes = {c for c, _ in Op.EngineOperator.choices}
        self.assertTrue({"between", "before", "after", "is_true", "is_false"} <= codes)
