from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from documents.models import ShopwareCmsPage, ShopwareCmsSlot
from documents.shopware_cms_service import ShopwareCmsPageService


class ShopwareCmsPageServiceParsingTests(SimpleTestCase):
    def test_extracts_static_html_slots_and_describes_layout(self):
        payload = {
            "id": "page-1",
            "name": "Über uns",
            "sections": [
                {
                    "position": 1,
                    "blocks": [
                        {
                            "position": 2,
                            "slots": [
                                {
                                    "id": "slot-html",
                                    "slot": "left",
                                    "type": "text",
                                    "config": {
                                        "content": {"source": "static", "value": "<p>Hallo</p>"}
                                    },
                                },
                                {
                                    "id": "slot-image",
                                    "slot": "right",
                                    "type": "image",
                                    "config": {"media": {"source": "static", "value": "media-id"}},
                                },
                            ],
                        }
                    ],
                }
            ],
        }

        slots = list(ShopwareCmsPageService._iter_slots(payload))

        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0]["slot_label"], "Abschnitt 1 · Block 2 · Slot left")
        self.assertEqual(ShopwareCmsPageService._editable_html(slots[0]["config"]), "<p>Hallo</p>")
        self.assertIsNone(ShopwareCmsPageService._editable_html(slots[1]["config"]))
        self.assertEqual(
            ShopwareCmsPageService._layout_description(slots),
            "2 Inhaltselemente (image: 1, text: 1). 1 HTML-Inhalte lokal bearbeitbar.",
        )

    def test_ignores_dynamic_content_slots(self):
        self.assertIsNone(
            ShopwareCmsPageService._editable_html(
                {"content": {"source": "mapped", "value": "<p>{{ product.name }}</p>"}}
            )
        )


class ShopwareCmsPageServiceSyncTests(SimpleTestCase):
    @patch.object(ShopwareCmsSlot, "save")
    def test_sync_updates_only_static_slot_content(self, mock_save):
        service = ShopwareCmsPageService.__new__(ShopwareCmsPageService)
        service.request_post = Mock()
        page = ShopwareCmsPage(shopware_id="page-1", title="Über uns")
        slot = ShopwareCmsSlot(
            page=page,
            shopware_id="slot-1",
            slot_type="text",
            slot_label="Abschnitt 1 · Block 1 · Slot main",
            html_content="<p>Neu</p>",
            remote_html_content="<p>Alt</p>",
            slot_config={"content": {"source": "static", "value": "<p>Alt</p>"}},
        )

        service.sync_slot(slot)

        service.request_post.assert_called_once_with(
            "/_action/sync",
            payload={
                "shop-page-slot-upsert": {
                    "entity": "cms_slot",
                    "action": "upsert",
                    "payload": [
                        {
                            "id": "slot-1",
                            "config": {"content": {"source": "static", "value": "<p>Neu</p>"}},
                        }
                    ],
                }
            },
        )
        self.assertEqual(slot.remote_html_content, "<p>Neu</p>")
        mock_save.assert_called_once()
