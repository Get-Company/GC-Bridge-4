import json

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
    MicrotechOrderRuleOperator,
    RuleTrigger,
)
from microtech.rule_engine.editor import (
    EditorValidationError, save_rule_from_payload, serialize_rule_for_edit,
)


class SerializeForEditTest(TestCase):
    def test_serializes_tree_with_ids_and_codes(self):
        trig = RuleTrigger.objects.create(code="ed_o", label="Bestellung",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        rule = MicrotechOrderRule.objects.create(name="R", trigger=trig)
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=root, django_field_path="total",
            operator_code="between", expected_value="5", expected_value_2="9")
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["trigger_id"], trig.id)
        self.assertEqual(data["root_group"]["logic"], "all")
        c = data["root_group"]["conditions"][0]
        self.assertEqual((c["field_path"], c["operator_code"], c["expected_value"], c["expected_value_2"]),
                         ("total", "between", "5", "9"))

    def test_multiple_roots_are_serialized_as_one_semantic_tree(self):
        rule = MicrotechOrderRule.objects.create(name="Mehrere Wurzeln")
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ANY)

        data = serialize_rule_for_edit(rule)

        self.assertEqual(data["root_group"]["logic"], MicrotechOrderRule.ConditionLogic.ALL)
        self.assertEqual(len(data["root_group"]["children"]), 2)

    def test_serializes_dataset_target_with_area_and_short_name(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="adressen", name="Adressen", source_identifier="Adressen - Adressen",
        )
        field = MicrotechDatasetField.objects.create(
            dataset=dataset, field_name="UStKat", label="Umsatzsteuerkategorie",
        )
        rule = MicrotechOrderRule.objects.create(name="Steuer")
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset_field=field,
            target_value="1",
        )

        action = serialize_rule_for_edit(rule)["actions"][0]

        self.assertEqual(
            action["dataset_field_label"],
            "Umsatzsteuerkategorie · Adressen.UStKat",
        )


class SaveFromPayloadTest(TestCase):
    def setUp(self):
        MicrotechOrderRuleOperator.objects.get_or_create(code="eq", defaults={"name": "==", "engine_operator": "eq"})
        MicrotechOrderRuleOperator.objects.get_or_create(code="between", defaults={"name": "between", "engine_operator": "between"})

    def _payload(self):
        return {
            "name": "Neu", "priority": 30, "is_active": True,
            "execution_phase": "before", "engine_enabled": False, "shadow_mode": True,
            "trigger_id": None,
            "root_group": {"logic": "all", "children": [
                {"logic": "any", "children": [], "conditions": [
                    {"field_path": "total", "operator_code": "between", "expected_value": "5", "expected_value_2": "9"}]}],
                "conditions": [{"field_path": "billing_address__country_code", "operator_code": "eq",
                                "expected_value": "CH", "expected_value_2": ""}]},
            "actions": [{"action_type": "create_shipping_position", "dataset_field_id": None, "target_value": "V"}],
        }

    def test_round_trip(self):
        rule = save_rule_from_payload(self._payload())
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["name"], "Neu")
        self.assertEqual(len(data["root_group"]["children"]), 1)
        self.assertEqual(data["root_group"]["children"][0]["conditions"][0]["operator_code"], "between")
        self.assertEqual(data["actions"][0]["target_value"], "V")

    def test_resave_replaces_tree(self):
        rule = save_rule_from_payload(self._payload())
        p2 = self._payload(); p2["root_group"]["children"] = []; p2["actions"] = []
        save_rule_from_payload(p2, rule=rule)
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["root_group"]["children"], [])
        self.assertEqual(data["actions"], [])

    def test_invalid_operator_rolls_back(self):
        p = self._payload(); p["root_group"]["conditions"][0]["operator_code"] = "nope"
        with self.assertRaises(EditorValidationError):
            save_rule_from_payload(p)

    def test_unknown_field_path_is_rejected(self):
        p = self._payload(); p["root_group"]["conditions"][0]["field_path"] = "does_not_exist"
        with self.assertRaises(EditorValidationError):
            save_rule_from_payload(p)

    def test_unknown_dataset_field_id_raises_validation_error(self):
        p = self._payload()
        p["actions"] = [{"action_type": "set_field", "dataset_field_id": 999999, "target_value": "V"}]
        rule_count_before = MicrotechOrderRule.objects.count()
        with self.assertRaises(EditorValidationError):
            save_rule_from_payload(p)
        self.assertEqual(MicrotechOrderRule.objects.count(), rule_count_before)

    def test_invalid_group_logic_raises_validation_error(self):
        p = self._payload(); p["root_group"]["logic"] = "nope"
        with self.assertRaises(EditorValidationError):
            save_rule_from_payload(p)

    def test_non_dict_group_payload_raises_validation_error(self):
        p = self._payload(); p["root_group"]["children"] = ["not-a-dict"]
        with self.assertRaises(EditorValidationError):
            save_rule_from_payload(p)

    def test_editor_save_removes_ungrouped_legacy_conditions(self):
        rule = MicrotechOrderRule.objects.create(name="Alt")
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, django_field_path="total", operator_code="eq", expected_value="1",
        )
        payload = self._payload()
        payload["root_group"] = {"logic": "all", "children": [], "conditions": []}
        payload["actions"] = []

        save_rule_from_payload(payload, rule=rule)

        self.assertEqual(rule.conditions.count(), 0)


class MetaTriggersTest(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username="admin_meta_triggers",
            email="admin_meta_triggers@example.com",
            password="secret123",
        )
        self.client.force_login(self.admin_user)

    def test_meta_includes_active_trigger(self):
        trig, _ = RuleTrigger.objects.get_or_create(
            code="test_meta_trigger",
            defaults={
                "label": "Test Meta Trigger",
                "task_name": "orders.microtech_order_upsert",
                "context_root": "orders.Order",
            },
        )
        response = self.client.get(reverse("admin:microtech_orderrule_builder_meta"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        triggers_by_code = {item["code"]: item for item in data["triggers"]}
        self.assertIn("test_meta_trigger", triggers_by_code)
        entry = triggers_by_code["test_meta_trigger"]
        self.assertEqual(entry["id"], trig.id)
        self.assertEqual(entry["label"], "Test Meta Trigger")
        self.assertEqual(entry["task_name"], "orders.microtech_order_upsert")
        self.assertEqual(entry["context_root"], "orders.Order")


class RuleEditorViewTest(TestCase):
    def setUp(self):
        MicrotechOrderRuleOperator.objects.get_or_create(
            code="eq", defaults={"name": "==", "engine_operator": "eq"}
        )
        MicrotechOrderRuleOperator.objects.get_or_create(
            code="between", defaults={"name": "between", "engine_operator": "between"}
        )
        self.admin_user = get_user_model().objects.create_superuser(
            username="admin_rule_editor",
            email="admin_rule_editor@example.com",
            password="secret123",
        )
        self.client.force_login(self.admin_user)

    def _payload(self):
        return {
            "name": "Editor-Regel", "priority": 30, "is_active": True,
            "execution_phase": "before", "engine_enabled": False, "shadow_mode": True,
            "trigger_id": None,
            "root_group": {"logic": "all", "children": [], "conditions": [
                {"field_path": "total", "operator_code": "between",
                 "expected_value": "5", "expected_value_2": "9"}]},
            "actions": [{"action_type": "create_shipping_position",
                         "dataset_field_id": None, "target_value": "V"}],
        }

    def test_get_editor_page_for_existing_rule(self):
        rule = MicrotechOrderRule.objects.create(name="Bestehend")
        response = self.client.get(
            reverse("admin:microtech_orderrule_editor", args=[rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="rule-data"', content)
        self.assertIn('id="re-conditions"', content)

    def test_get_editor_page_for_new_rule(self):
        response = self.client.get(
            reverse("admin:microtech_orderrule_editor_new")
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="rule-data"', content)
        self.assertIn('id="re-conditions"', content)

    def test_post_save_valid_payload_creates_rule(self):
        response = self.client.post(
            reverse("admin:microtech_orderrule_editor_save"),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        rule = MicrotechOrderRule.objects.get(pk=data["id"])
        self.assertEqual(rule.name, "Editor-Regel")
        self.assertEqual(rule.actions.count(), 1)

    def test_post_save_invalid_payload_returns_400(self):
        payload = self._payload()
        payload["root_group"]["conditions"][0]["operator_code"] = "not-a-real-code"
        response = self.client.post(
            reverse("admin:microtech_orderrule_editor_save"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertTrue(data["errors"])

    def test_post_save_malformed_json_returns_400(self):
        response = self.client.post(
            reverse("admin:microtech_orderrule_editor_save"),
            data=b"{kaputt",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])

    def test_post_save_with_stale_id_returns_404_and_does_not_create(self):
        payload = self._payload()
        payload["id"] = 999999
        rule_count_before = MicrotechOrderRule.objects.count()
        response = self.client.post(
            reverse("admin:microtech_orderrule_editor_save"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(MicrotechOrderRule.objects.count(), rule_count_before)

    def test_post_save_with_unknown_dataset_field_id_returns_400_not_500(self):
        payload = self._payload()
        payload["actions"] = [{"action_type": "set_field", "dataset_field_id": 999999, "target_value": "V"}]
        rule_count_before = MicrotechOrderRule.objects.count()
        response = self.client.post(
            reverse("admin:microtech_orderrule_editor_save"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(MicrotechOrderRule.objects.count(), rule_count_before)
