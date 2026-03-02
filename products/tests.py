from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from products.admin import PriceAdmin
from products.models import Price


class PriceAdminActionTest(TestCase):
    def test_percent_sign_in_action_description_does_not_crash(self):
        user_model = get_user_model()
        user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        request = RequestFactory().get("/admin/products/price/")
        request.user = user

        admin_instance = PriceAdmin(Price, AdminSite())
        choices = dict(admin_instance.get_action_choices(request))

        self.assertEqual(choices["set_special_price_bulk"], "Sonderpreis setzen (%)")
