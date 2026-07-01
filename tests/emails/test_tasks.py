from datetime import timedelta
from unittest.mock import patch


class TestEmailCampaignTasks:
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
