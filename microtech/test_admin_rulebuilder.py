from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class MicrotechOrderRuleAdminAutocompleteTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret123",
        )
        self.client.force_login(self.admin_user)

    def test_add_view_renders_unfold_autocomplete_fields(self):
        response = self.client.get(reverse("admin:microtech_microtechorderrule_add"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('name="conditions-__prefix__-django_field_path"', content)
        self.assertIn('name="actions-__prefix__-dataset_field"', content)
        self.assertIn("admin-autocomplete", content)
        self.assertIn("microtechorderrule/django-field-autocomplete/", content)
        self.assertIn("microtechorderrule/dataset-field-autocomplete/", content)
