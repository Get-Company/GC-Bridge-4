from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup,
    RuleTrigger,
)
from microtech.rule_engine.overview import serialize_rules_for_overview


class RuleBuilderOverviewSerializerTest(TestCase):
    def test_serialize_nested_rule(self):
        trigger = RuleTrigger.objects.create(
            code="ov_order", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        rule = MicrotechOrderRule.objects.create(
            name="Schweiz-Regel", trigger=trigger,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL)
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        sub = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, parent=root, logic=MicrotechOrderRule.ConditionLogic.ANY)
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=root, django_field_path="billing_address__country_code",
            operator_code="eq", expected_value="CH")
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="total",
            operator_code="between", expected_value="500", expected_value_2="9999")

        data = serialize_rules_for_overview()
        self.assertEqual(len(data), 1)
        r = data[0]
        self.assertEqual(r["name"], "Schweiz-Regel")
        self.assertEqual(r["trigger"]["label"], "Bestellung anlegen")
        self.assertTrue(r["has_conditions"])
        # root group has one condition + one child group
        self.assertEqual(len(r["root_groups"]), 1)
        root_data = r["root_groups"][0]
        self.assertEqual(len(root_data["conditions"]), 1)
        self.assertEqual(len(root_data["children"]), 1)
        # between condition renders both bounds
        between = root_data["children"][0]["conditions"][0]
        self.assertIn("500", between["value"])
        self.assertIn("9999", between["value"])

    def test_variable_detection_in_action(self):
        rule = MicrotechOrderRule.objects.create(name="R")
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        MicrotechOrderRuleAction.objects.create(
            rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            target_value="{{ Kunde.Firma }}")
        r = serialize_rules_for_overview()[0]
        self.assertTrue(r["actions"][0]["value_is_variable"])

    def test_dataset_action_identifies_area_and_short_name(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgang_vorgange",
            name="Vorgang",
            source_identifier="Vorgang - Vorgange",
        )
        field = MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="UStKat",
            label="Umsatzsteuerkategorie",
        )
        rule = MicrotechOrderRule.objects.create(name="Steuer")
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset_field=field,
            target_value="1",
        )

        action = serialize_rules_for_overview()[0]["actions"][0]

        self.assertEqual(
            action["field"],
            "Umsatzsteuerkategorie · Vorgang.UStKat",
        )


class RuleBuilderOverviewViewTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="ov_root", email="ov@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_builder_page_renders_rule(self):
        MicrotechOrderRule.objects.create(name="Sichtbare-Regel")
        response = self.client.get(reverse("admin:microtech_orderrule_builder"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sichtbare-Regel")
