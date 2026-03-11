from django.test import TestCase
from microtech.forms import MicrotechOrderRuleActionForm, MicrotechOrderRuleConditionForm
from microtech.models import MicrotechDatasetCatalog, MicrotechDatasetField, MicrotechOrderRuleAction, MicrotechOrderRuleDjangoField
from microtech.rule_builder import sync_django_field_catalog


class MicrotechOrderRuleFormsTest(TestCase):
    def _field_catalog_id(self, field_path: str) -> int:
        sync_django_field_catalog()
        return MicrotechOrderRuleDjangoField.objects.get(field_path=field_path).pk

    def test_condition_form_uses_catalog_relation_field(self):
        form = MicrotechOrderRuleConditionForm()

        self.assertIn("django_field", form.fields)
        self.assertNotIn("django_field_path", form.fields)

    def test_condition_form_accepts_equals_alias(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("payment_method"),
                "operator_code": "equals",
                "expected_value": "paypal",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_condition_form_accepts_django_field_path(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("payment_method"),
                "operator_code": "contains",
                "expected_value": "paypal",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_condition_form_rejects_disallowed_operator_for_bool_field(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("customer__is_gross"),
                "operator_code": "contains",
                "expected_value": "true",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("operator_code", form.errors)
        self.assertNotIn("django_field", form.errors)

    def test_action_form_validates_set_field_dataset_binding(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgang_vorgange",
            name="Vorgang",
            description="Vorgange",
            source_identifier="Vorgang - Vorgange",
            priority=10,
        )
        field = MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="ZahlArt",
            label="Zahlungsart",
            field_type="Integer",
            priority=10,
        )

        form = MicrotechOrderRuleActionForm(
            data={
                "is_active": True,
                "priority": 10,
                "action_type": MicrotechOrderRuleAction.ActionType.SET_FIELD,
                "dataset": dataset.id,
                "dataset_field": field.id,
                "target_value": "22",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_action_form_requires_erp_nr_for_create_extra_position(self):
        form = MicrotechOrderRuleActionForm(
            data={
                "is_active": True,
                "priority": 10,
                "action_type": MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION,
                "target_value": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("target_value", form.errors)

    def test_action_form_derives_dataset_from_dataset_field(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgangposition_vorgangspositionen",
            name="VorgangPosition",
            description="Vorgangspositionen",
            source_identifier="VorgangPosition - Vorgangspositionen",
            priority=10,
        )
        field = MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="KuBez",
            label="Kurzbezeichnung",
            field_type="UnicodeString",
            priority=10,
        )

        form = MicrotechOrderRuleActionForm(
            data={
                "is_active": True,
                "priority": 10,
                "action_type": MicrotechOrderRuleAction.ActionType.SET_FIELD,
                "dataset_field": field.id,
                "target_value": "PayPal Gebuehr",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(form.cleaned_data["dataset"], dataset)

    def test_action_form_keeps_dataset_field_model_field(self):
        form = MicrotechOrderRuleActionForm()

        self.assertIn("dataset_field", form.fields)
