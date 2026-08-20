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
