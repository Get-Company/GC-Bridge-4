from datetime import timedelta
from unittest.mock import patch


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
