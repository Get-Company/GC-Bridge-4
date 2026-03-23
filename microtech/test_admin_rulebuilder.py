from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleOperator,
)
from microtech.rule_builder import sync_django_field_catalog


class MicrotechOrderRuleAdminAutocompleteTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret123",
        )
        self.client.force_login(self.admin_user)
        sync_django_field_catalog()
        dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgang_vorgange",
            name="Vorgang",
            description="Vorgange",
            source_identifier="Vorgang - Vorgange",
            priority=10,
        )
        MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="ZahlArt",
            label="Zahlungsart",
            field_type="Integer",
            priority=10,
        )
        MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="CalcFoo",
            label="Berechnet",
            field_type="Integer",
            is_calc_field=True,
            priority=20,
        )
        MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="ReadOnlyFoo",
            label="Nur Lesen",
            field_type="Integer",
            can_access=False,
            priority=30,
        )
        position_dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgangposition_vorgangspositionen",
            name="VorgangPosition",
            description="Vorgangspositionen",
            source_identifier="VorgangPosition - Vorgangspositionen",
            priority=20,
        )
        MicrotechDatasetField.objects.create(
            dataset=position_dataset,
            field_name="KuBez",
            label="Kurzbezeichnung",
            field_type="UnicodeString",
            priority=10,
        )
        for priority, code, name in (
            (10, "equals", "="),
            (20, "contains", "enthaelt"),
            (30, "is_empty", "ist leer"),
            (40, "is_not_empty", "ist nicht leer"),
            (50, "ne", "!="),
            (60, "gt", ">"),
        ):
            MicrotechOrderRuleOperator.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "engine_operator": "eq" if code == "equals" else code,
                    "priority": priority,
                    "is_active": True,
                },
            )

    def test_add_view_renders_unfold_autocomplete_fields(self):
        response = self.client.get(reverse("admin:microtech_microtechorderrule_add"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('name="conditions-__prefix__-django_field"', content)
        self.assertIn('name="conditions-__prefix__-operator"', content)
        self.assertIn('name="actions-__prefix__-ui_action"', content)
        self.assertIn('name="actions-__prefix__-dataset_field"', content)
        self.assertIn("admin-autocomplete", content)
        self.assertIn('data-app-label="microtech"', content)
        self.assertIn('data-field-name="django_field"', content)
        self.assertIn('data-field-name="dataset_field"', content)
        self.assertIn("rulebuilder-operator-autocomplete", content)
        self.assertIn("rulebuilder-dataset-field-autocomplete", content)
        self.assertIn("/admin/microtech/microtechorderrule/operator-autocomplete/", content)
        self.assertIn("/admin/microtech/microtechorderrule/dataset-field-autocomplete/", content)
        self.assertIn("Regel-Zusammenfassung", content)
        self.assertNotIn("tabular-table", content)
        self.assertIn("stacked", content)

    def test_operator_autocomplete_is_filtered_by_selected_django_field(self):
        django_field_id = MicrotechOrderRuleDjangoField.objects.get(field_path="payment_method").pk

        response = self.client.get(
            reverse("admin:microtech_orderrule_operator_autocomplete"),
            {"django_field_id": django_field_id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rendered = " ".join(item.get("text", "") for item in payload.get("results", []))
        self.assertIn("equals", rendered)
        self.assertIn("contains", rendered)
        self.assertIn("is_empty", rendered)
        self.assertIn("is_not_empty", rendered)
        self.assertIn("ne", rendered)
        self.assertNotIn("gt", rendered)

    def test_dataset_field_autocomplete_is_filtered_by_action_target(self):
        response = self.client.get(
            reverse("admin:microtech_orderrule_dataset_field_autocomplete"),
            {"action_target": "set_vorgang_field"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rendered = " ".join(item.get("text", "") for item in payload.get("results", []))
        self.assertIn("Vorgang.ZahlArt - Zahlungsart", rendered)
        self.assertNotIn("CalcFoo", rendered)
        self.assertNotIn("ReadOnlyFoo", rendered)
        self.assertNotIn("KuBez", rendered)

    def test_dataset_field_autocomplete_supports_dataset_dot_field_search(self):
        response = self.client.get(
            reverse("admin:microtech_orderrule_dataset_field_autocomplete"),
            {
                "action_target": "set_vorgang_field",
                "term": "Vorgang.ZahlArt",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rendered = " ".join(item.get("text", "") for item in payload.get("results", []))
        self.assertIn("Vorgang.ZahlArt - Zahlungsart", rendered)

    def test_dataset_field_autocomplete_supports_label_search(self):
        response = self.client.get(
            reverse("admin:microtech_orderrule_dataset_field_autocomplete"),
            {
                "action_target": "set_vorgang_field",
                "term": "Zahlungsart",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rendered = " ".join(item.get("text", "") for item in payload.get("results", []))
        self.assertIn("Vorgang.ZahlArt - Zahlungsart", rendered)
