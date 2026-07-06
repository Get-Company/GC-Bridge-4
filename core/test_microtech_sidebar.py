from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse


class _SidebarUser:
    is_active = True
    is_staff = True
    is_authenticated = True
    is_superuser = False
    employee_profile = None

    def __init__(self, permissions=None):
        self.permissions = set(permissions or [])
        self.groups = self._Groups()

    def has_perm(self, permission):
        return permission in self.permissions

    class _Groups:
        @staticmethod
        def filter(**_kwargs):
            return _SidebarUser._GroupQuerySet()

    class _GroupQuerySet:
        @staticmethod
        def exists():
            return False


class MicrotechSidebarTest(SimpleTestCase):
    def test_microtech_connection_sidebar_entry_uses_connection_view(self):
        request = RequestFactory().get(reverse("admin:index"))
        request.user = _SidebarUser({"microtech.view_microtechsettings"})

        item = [
            item
            for group in admin.site.get_sidebar_list(request)
            if str(group.get("title")) == "Microtech"
            for item in group.get("items", [])
            if str(item.get("title")) == "Verbindung"
        ][0]

        self.assertTrue(item["has_permission"])
        self.assertEqual(str(item["link"]), reverse("admin:core_microtech_connection"))
