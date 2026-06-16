from types import SimpleNamespace

from django.test import SimpleTestCase

from emails.admin import EmailCampaignSalesChannelInline


class EmailCampaignSalesChannelInlineTest(SimpleTestCase):
    def test_is_default_display_renders_default_channel_badge(self):
        obj = SimpleNamespace(
            sales_channel_id=1,
            sales_channel=SimpleNamespace(is_default=True),
        )

        html = EmailCampaignSalesChannelInline.is_default_display(None, obj)

        self.assertIn("Standard", html)
        self.assertIn("16a34a", html)

    def test_is_default_display_returns_dash_for_non_default_channel(self):
        obj = SimpleNamespace(
            sales_channel_id=1,
            sales_channel=SimpleNamespace(is_default=False),
        )

        self.assertEqual(EmailCampaignSalesChannelInline.is_default_display(None, obj), "—")
