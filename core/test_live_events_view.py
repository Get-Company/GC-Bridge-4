from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class LiveEventsApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True, is_superuser=True
        )
        self.plain = User.objects.create_user(username="plain", password="pw")

    def test_api_requires_staff(self):
        self.client.login(username="plain", password="pw")
        resp = self.client.get(reverse("admin:core_live_events_api"))
        self.assertIn(resp.status_code, (302, 403))

    def test_api_returns_events_after_id(self):
        self.client.login(username="staff", password="pw")
        # xread liefert [(stream_key, [(id, {field: value}), ...])]
        fake_redis = mock.MagicMock()
        fake_redis.xread.return_value = [
            ("live:events", [("5-0", {
                "ts": "1.0", "task": "products.auto_sync", "run_id": "r1",
                "entity": "4711", "target": "shopware6", "step": "→ shopware6",
                "status": "ok", "summary": "OK", "payload": "",
            })])
        ]
        with mock.patch("core.live_events_view._get_redis", return_value=fake_redis):
            resp = self.client.get(reverse("admin:core_live_events_api"), {"after": "4-0"})
        data = resp.json()
        self.assertEqual(data["next_id"], "5-0")
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["entity"], "4711")
        self.assertNotIn("payload", data["events"][0])  # payload nur im Detail-Endpunkt

    def test_api_filters_by_task(self):
        self.client.login(username="staff", password="pw")
        fake_redis = mock.MagicMock()
        fake_redis.xread.return_value = [
            ("live:events", [
                ("6-0", {"task": "orders.upsert", "entity": "A", "status": "ok",
                         "step": "s", "summary": "x", "run_id": "", "target": "", "ts": "1"}),
                ("7-0", {"task": "products.auto_sync", "entity": "B", "status": "ok",
                         "step": "s", "summary": "y", "run_id": "", "target": "", "ts": "1"}),
            ])
        ]
        with mock.patch("core.live_events_view._get_redis", return_value=fake_redis):
            resp = self.client.get(
                reverse("admin:core_live_events_api"),
                {"after": "0", "task": "products.auto_sync"},
            )
        data = resp.json()
        self.assertEqual([e["entity"] for e in data["events"]], ["B"])
        self.assertEqual(data["next_id"], "7-0")

    def test_live_events_page_renders(self):
        self.client.login(username="staff", password="pw")
        resp = self.client.get(reverse("admin:core_live_events"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "live-events-log")
