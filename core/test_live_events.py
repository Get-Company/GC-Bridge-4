# core/test_live_events.py
from unittest import mock

from django.test import SimpleTestCase

from core import live_events


class SerializePayloadTests(SimpleTestCase):
    def test_none_payload_serializes_to_empty_string(self):
        self.assertEqual(live_events._serialize_payload(None), "")

    def test_dict_payload_serializes_to_json(self):
        result = live_events._serialize_payload({"price": 12})
        self.assertIn('"price": 12', result)

    def test_oversized_payload_is_truncated(self):
        big = {"blob": "x" * 40000}
        result = live_events._serialize_payload(big)
        self.assertLessEqual(len(result.encode("utf-8")), live_events.PAYLOAD_MAX_BYTES)
        self.assertIn("_truncated", result)


class EmitEventTests(SimpleTestCase):
    def test_emit_event_writes_to_stream(self):
        fake_redis = mock.MagicMock()
        with mock.patch.object(live_events, "_get_redis", return_value=fake_redis):
            live_events.emit_event(
                task="products.auto_sync",
                entity="4711",
                step="→ shopware6",
                status="ok",
                summary="Produkt 4711 nach Shopware6 geschrieben",
                run_id="run-1",
                target="shopware6",
            )
        fake_redis.xadd.assert_called_once()
        args, kwargs = fake_redis.xadd.call_args
        self.assertEqual(args[0], live_events.LIVE_EVENTS_STREAM_KEY)
        fields = args[1]
        self.assertEqual(fields["task"], "products.auto_sync")
        self.assertEqual(fields["entity"], "4711")
        self.assertEqual(fields["status"], "ok")
        self.assertEqual(kwargs["maxlen"], live_events.STREAM_MAXLEN)
        self.assertTrue(kwargs["approximate"])

    def test_emit_event_never_raises_on_redis_error(self):
        fake_redis = mock.MagicMock()
        fake_redis.xadd.side_effect = RuntimeError("redis down")
        with mock.patch.object(live_events, "_get_redis", return_value=fake_redis):
            # Must not raise
            live_events.emit_event(
                task="t", entity="e", step="s", status="info", summary="x"
            )
