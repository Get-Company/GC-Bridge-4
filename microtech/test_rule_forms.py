from django.test import SimpleTestCase

from microtech.forms import MicrotechOrderRuleActionForm, MicrotechOrderRuleConditionForm


class MicrotechOrderRuleFormsTest(SimpleTestCase):
    def test_condition_form_normalizes_customer_type_alias(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "source_field": "customer_type",
                "operator": "eq",
                "expected_value": "Firma",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(form.cleaned_data["expected_value"], "company")

    def test_condition_form_rejects_contains_for_decimal_field(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "source_field": "order_total",
                "operator": "contains",
                "expected_value": "100",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("operator", form.errors)

    def test_action_form_normalizes_bool_values(self):
        form = MicrotechOrderRuleActionForm(
            data={
                "is_active": True,
                "priority": 10,
                "target_field": "add_payment_position",
                "target_value": "Ja",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(form.cleaned_data["target_value"], "true")

    def test_action_form_rejects_invalid_enum(self):
        form = MicrotechOrderRuleActionForm(
            data={
                "is_active": True,
                "priority": 10,
                "target_field": "payment_position_mode",
                "target_value": "percentage",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("target_value", form.errors)
