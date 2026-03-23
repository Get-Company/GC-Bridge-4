from django.test import TestCase
from microtech.forms import LEGACY_UI_ACTION, MicrotechOrderRuleActionForm, MicrotechOrderRuleConditionForm
from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleDjangoFieldPolicy,
    MicrotechOrderRuleOperator,
)
from microtech.rule_builder import (
    RULE_ACTION_TARGET_CREATE_EXTRA_POSITION,
    RULE_ACTION_TARGET_VORGANG_FIELD,
    RULE_ACTION_TARGET_VORGANG_POSITION_FIELD,
    sync_django_field_catalog,
)


class MicrotechOrderRuleFormsTest(TestCase):
    def _field_catalog_id(self, field_path: str) -> int:
        sync_django_field_catalog()
        return MicrotechOrderRuleDjangoField.objects.get(field_path=field_path).pk

    def _operator_id(self, code: str, name: str | None = None) -> int:
        operator, _ = MicrotechOrderRuleOperator.objects.get_or_create(
            code=code,
            defaults={
                "name": name or code,
                "engine_operator": "eq" if code in {"eq", "equals"} else code,
                "priority": 10,
                "is_active": True,
            },
        )
        return operator.pk

    def test_condition_form_uses_catalog_relation_field(self):
        form = MicrotechOrderRuleConditionForm()

        self.assertIn("django_field", form.fields)
        self.assertIn("operator", form.fields)
        self.assertIn("rulebuilder-operator-autocomplete", form.fields["operator"].widget.attrs.get("class", ""))
        self.assertIn("data-operator-autocomplete-url", form.fields["operator"].widget.attrs)

    def test_condition_form_marks_bool_input_with_value_kind_metadata(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("customer__is_gross"),
                "operator": self._operator_id("eq", "=="),
                "expected_value": "true",
            }
        )

        self.assertEqual(form.fields["expected_value"].widget.attrs.get("data-rulebuilder-value-kind"), "bool")

    def test_condition_form_uses_friendly_date_input_for_purchase_date(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("purchase_date"),
                "operator": self._operator_id("lt", "<"),
                "expected_value": "2026-03-23",
            }
        )

        self.assertEqual(form.fields["expected_value"].widget.attrs.get("data-rulebuilder-input-type"), "date")
        self.assertEqual(form.fields["expected_value"].widget.attrs.get("type"), "date")
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_condition_form_uses_friendly_country_label_override(self):
        sync_django_field_catalog()
        field = MicrotechOrderRuleDjangoField.objects.get(field_path="billing_address__country_code")
        self.assertEqual(field.label, "Rechnungsland")

    def test_condition_form_keeps_datetime_input_for_existing_purchase_date_time_value(self):
        condition = MicrotechOrderRuleCondition(
            django_field_path="purchase_date",
            expected_value="2026-03-23T15:45:00",
        )
        form = MicrotechOrderRuleConditionForm(instance=condition)

        self.assertEqual(form.fields["expected_value"].widget.attrs.get("type"), "datetime-local")

    def test_condition_form_accepts_equals_alias(self):
        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("payment_method"),
                "operator": self._operator_id("equals", "="),
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
                "operator": self._operator_id("contains", "enthaelt"),
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
                "operator": self._operator_id("contains", "enthaelt"),
                "expected_value": "true",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("operator", form.errors)
        self.assertNotIn("django_field", form.errors)

    def test_condition_form_rejects_operator_blocked_by_field_policy(self):
        equals_id = self._operator_id("eq", "==")
        contains_id = self._operator_id("contains", "enthaelt")
        policy = MicrotechOrderRuleDjangoFieldPolicy.objects.create(
            field_path="payment_method",
            label_override="Zahlungsart",
            hint="Nur exakte Vergleiche",
            priority=10,
            is_active=True,
        )
        policy.allowed_operators.add(MicrotechOrderRuleOperator.objects.get(pk=equals_id))

        form = MicrotechOrderRuleConditionForm(
            data={
                "is_active": True,
                "priority": 10,
                "django_field": self._field_catalog_id("payment_method"),
                "operator": contains_id,
                "expected_value": "paypal",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("operator", form.errors)

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
                "ui_action": RULE_ACTION_TARGET_VORGANG_FIELD,
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
                "ui_action": RULE_ACTION_TARGET_CREATE_EXTRA_POSITION,
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
                "ui_action": RULE_ACTION_TARGET_VORGANG_POSITION_FIELD,
                "dataset_field": field.id,
                "target_value": "PayPal Gebuehr",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(form.cleaned_data["dataset"], dataset)

    def test_action_form_rejects_dataset_field_for_wrong_action_target(self):
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
                "ui_action": RULE_ACTION_TARGET_VORGANG_FIELD,
                "dataset_field": field.id,
                "target_value": "Falsch",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("dataset_field", form.errors)

    def test_action_form_keeps_legacy_set_field_action_editable(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="artikel_artikel",
            name="Artikel",
            description="Artikel",
            source_identifier="Artikel - Artikel",
            priority=10,
        )
        field = MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="Bez",
            label="Bezeichnung",
            field_type="UnicodeString",
            priority=10,
        )
        action = MicrotechOrderRuleAction(
            action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset=dataset,
            dataset_field=field,
            target_value="Altwert",
        )

        form = MicrotechOrderRuleActionForm(
            instance=action,
            data={
                "is_active": True,
                "priority": 10,
                "ui_action": LEGACY_UI_ACTION,
                "dataset_field": field.id,
                "target_value": "Altwert",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(form.cleaned_data["dataset"], dataset)

    def test_action_form_filters_non_writable_dataset_fields(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgang_vorgange",
            name="Vorgang",
            description="Vorgange",
            source_identifier="Vorgang - Vorgange",
            priority=10,
        )
        writable = MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="ZahlArt",
            label="Zahlungsart",
            field_type="Integer",
            can_access=True,
            is_calc_field=False,
            priority=10,
        )
        MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="CalcFoo",
            label="Berechnet",
            field_type="Integer",
            can_access=True,
            is_calc_field=True,
            priority=20,
        )
        MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="ReadOnlyFoo",
            label="Nur Lesen",
            field_type="Integer",
            can_access=False,
            is_calc_field=False,
            priority=30,
        )

        form = MicrotechOrderRuleActionForm(
            data={
                "is_active": True,
                "priority": 10,
                "ui_action": RULE_ACTION_TARGET_VORGANG_FIELD,
                "target_value": "22",
            }
        )

        queryset = form.fields["dataset_field"].queryset
        self.assertIn(writable, list(queryset))
        self.assertEqual(queryset.count(), 1)

    def test_action_form_keeps_dataset_field_model_field(self):
        form = MicrotechOrderRuleActionForm()

        self.assertIn("ui_action", form.fields)
        self.assertIn("dataset_field", form.fields)
