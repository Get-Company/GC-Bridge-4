from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from microtech.models import RuleTrigger


class RuleTriggerAdminTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root", email="root@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_changelist_and_add_render(self):
        RuleTrigger.objects.create(
            code="order_create_admin_test", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        list_url = reverse("admin:microtech_ruletrigger_changelist")
        add_url = reverse("admin:microtech_ruletrigger_add")
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(add_url).status_code, 200)


class RuleConstantAdminTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root2", email="root2@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_changelist_and_add_render(self):
        from microtech.models import RuleConstant
        RuleConstant.objects.update_or_create(
            key="eu_country_codes", defaults={"value": "DE,IT", "kind": "list"})
        from django.urls import reverse
        self.assertEqual(
            self.client.get(reverse("admin:microtech_ruleconstant_changelist")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:microtech_ruleconstant_add")).status_code, 200)


class ConditionGroupAdminTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root3", email="root3@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_changelist_and_add_render(self):
        from django.urls import reverse
        from microtech.models import MicrotechOrderRule, MicrotechOrderRuleConditionGroup
        rule = MicrotechOrderRule.objects.create(name="R")
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        self.assertEqual(
            self.client.get(reverse(
                "admin:microtech_microtechorderruleconditiongroup_changelist")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse(
                "admin:microtech_microtechorderruleconditiongroup_add")).status_code, 200)


class OrderRuleAdminEngineFieldsTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root4", email="root4@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_change_form_exposes_new_engine_fields(self):
        from django.urls import reverse
        from microtech.models import MicrotechOrderRule
        rule = MicrotechOrderRule.objects.create(name="R")
        html = self.client.get(
            reverse("admin:microtech_microtechorderrule_change", args=(rule.pk,))).content.decode()
        for field in ("trigger", "execution_phase", "shadow_mode", "engine_enabled"):
            self.assertIn(f'name="{field}"', html)
