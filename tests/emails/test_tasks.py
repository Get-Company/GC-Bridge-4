from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestEmailCampaignTasks:
    @patch("products.tasks.shopware_sync_products.delay")
    @patch("products.tasks.microtech_update_prices.delay")
    @patch("emails.services.apply_campaign_special_prices", return_value=["581000", "581001"])
    @patch("emails.models.EmailCampaign.objects.get")
    def test_apply_prices_syncs_both_external_systems(
        self,
        campaign_get,
        apply_prices,
        microtech_delay,
        shopware_delay,
    ):
        from emails.tasks import apply_campaign_prices_async

        campaign = campaign_get.return_value

        apply_campaign_prices_async.run(3)

        apply_prices.assert_called_once_with(campaign)
        microtech_delay.assert_called_once_with(["581000", "581001"])
        shopware_delay.assert_called_once_with(["581000", "581001"], skip_images=True)

    def test_due_campaign_price_is_published_to_shopware_at_send_date(self):
        from emails.models import EmailCampaign
        from emails.tasks import sync_due_campaign_prices_to_shopware

        send_at = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)
        now = datetime(2026, 10, 6, 0, 1, tzinfo=UTC)
        item = SimpleNamespace(
            pk=8,
            product=SimpleNamespace(erp_nr="581000"),
            special_price_override=None,
            discount_pct=Decimal("5.00"),
            updated_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        )
        campaign = SimpleNamespace(
            pk=3,
            send_at=send_at,
            status=EmailCampaign.Status.READY,
            shopware_price_activation_fingerprint="",
            discount_products=[item],
        )
        campaigns = MagicMock()
        campaigns.prefetch_related.return_value = campaigns
        campaigns.order_by.return_value = [campaign]
        update_query = MagicMock()
        update_query.filter.return_value = update_query
        update_query.update.return_value = 1
        product_items = MagicMock()
        product_items.select_related.return_value = product_items

        with (
            patch("emails.tasks.timezone.now", return_value=now),
            patch(
                "emails.models.EmailCampaign.objects.filter",
                side_effect=[campaigns, update_query],
            ),
            patch(
                "emails.models.EmailCampaignProduct.objects.filter",
                return_value=product_items,
            ),
            patch("emails.tasks.Prefetch", return_value=object()),
            patch(
                "emails.services._end_of_next_month",
                return_value=datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC),
            ),
            patch("emails.services.apply_campaign_special_prices", return_value=[]),
            patch("emails.tasks.call_command") as call_command,
        ):
            summary = sync_due_campaign_prices_to_shopware.run()

        assert summary == {
            "campaigns": 1,
            "activated": 1,
            "expired": 0,
            "skipped": 0,
            "failed": 0,
        }
        call_command.assert_called_once_with(
            "shopware_sync_products",
            "581000",
            skip_images=True,
        )
        update_query.update.assert_called_once()

    def test_price_activation_worker_is_scheduled_every_minute_on_bulk_queue(self):
        from django.conf import settings

        schedule = settings.CELERY_BEAT_SCHEDULE[
            "email-campaign-prices-to-shopware-every-minute"
        ]

        assert schedule == {
            "task": "emails.sync_due_campaign_prices_to_shopware",
            "schedule": 60.0,
            "options": {"queue": "bulk"},
        }
        assert settings.CELERY_TASK_ROUTES[
            "emails.sync_due_campaign_prices_to_shopware"
        ] == {"queue": "bulk"}

    def test_expiry_uses_a_new_fingerprint_for_normal_price_restore(self):
        from emails.tasks import _shopware_activation_fingerprint

        campaign = SimpleNamespace(
            pk=3,
            send_at=datetime(2026, 10, 6, 0, 0, tzinfo=UTC),
        )
        item = SimpleNamespace(
            pk=8,
            product=SimpleNamespace(erp_nr="581000"),
            special_price_override=None,
            discount_pct=Decimal("5.00"),
            updated_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        )

        active = _shopware_activation_fingerprint(campaign, [item], phase="active")
        expired = _shopware_activation_fingerprint(campaign, [item], phase="expired")

        assert active != expired

    @patch("emails.services.EmailCampaignQueueService")
    def test_queue_due_campaigns_before_send_delegates_to_service(self, queue_service_class):
        from emails.tasks import queue_due_campaigns_before_send

        queue_service = queue_service_class.return_value
        queue_service.queue_due_campaigns_before_send.return_value = {
            "campaigns": 1,
            "recipients": 2,
            "queued": 2,
            "failed": 0,
        }

        result = queue_due_campaigns_before_send.run(lead_time_hours=24, window_minutes=90)

        assert result == {
            "campaigns": 1,
            "recipients": 2,
            "queued": 2,
            "failed": 0,
        }
        queue_service.queue_due_campaigns_before_send.assert_called_once_with(
            lead_time=timedelta(hours=24),
            window=timedelta(minutes=90),
        )
