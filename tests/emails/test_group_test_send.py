from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from emails.models import EmailCampaign, EmailCampaignQueueEntry, EmailSmtpSettings
from emails.services import EmailCampaignSendService, EmailCampaignTestQueueService
from newsletter.models import NewsletterRecipient, NewsletterRecipientGroup


@pytest.fixture
def test_group():
    campaign = EmailCampaign.objects.create(
        internal_title="November", subject="Hybride Arbeitswelt", status=EmailCampaign.Status.DRAFT
    )
    group = NewsletterRecipientGroup.objects.create(
        name="Redaktion", test_email_campaign=campaign
    )
    recipient = NewsletterRecipient.objects.create(
        shopware_id="person-1", email="one@example.com", status=NewsletterRecipient.Status.OPT_IN
    )
    group.members.add(recipient)
    EmailSmtpSettings.objects.create(
        is_active=False, host="smtp.example.com", sender_email="newsletter@example.com"
    )
    return campaign, group, recipient


@pytest.fixture
def render():
    with patch("emails.services.render_campaign_mjml", return_value="<mjml>draft</mjml>"), patch(
        "emails.services.compile_mjml_to_html", return_value="<p>draft</p>"
    ), patch("emails.services.html_to_plain_text", return_value="draft"):
        yield


@pytest.mark.django_db
def test_test_group_uses_same_queue_and_worker_without_enabling_series(test_group, render, settings):
    campaign, group, recipient = test_group
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    queued = EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
    entry = EmailCampaignQueueEntry.objects.get()
    assert queued == {"queued": 1, "skipped": 0, "failed": 0}
    assert entry.test_batch is not None
    assert entry.test_group == group
    assert entry.status == EmailCampaignQueueEntry.Status.QUEUED

    connection = MagicMock()
    connection.send_messages.return_value = 1
    shopware = MagicMock()
    shopware.request_post.return_value = {
        "data": [{"id": recipient.shopware_id, "status": "optIn", "email": recipient.email}]
    }
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService", return_value=shopware), patch(
        "emails.services.EmailSmtpSettingsService.build_connection", return_value=connection
    ):
        result = EmailCampaignSendService().send_due_entries()

    entry.refresh_from_db()
    assert result["sent"] == 1
    assert entry.status == EmailCampaignQueueEntry.Status.SENT
    assert entry.attempt_count == 1
    assert entry.sent_at is not None
    message = connection.send_messages.call_args.args[0][0]
    assert message.to == [recipient.email]
    assert message.subject == "[Test] Hybride Arbeitswelt"
    assert message.body == "draft"
    assert message.alternatives[0].content == "<p>draft</p>"
    campaign.refresh_from_db()
    assert campaign.status == EmailCampaign.Status.DRAFT
    assert campaign.send_at is None
    assert not EmailSmtpSettings.objects.get(pk=1).is_active


@pytest.mark.django_db
def test_removed_member_is_cancelled_before_smtp(test_group, render, settings):
    campaign, group, recipient = test_group
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
    group.members.remove(recipient)
    with patch("emails.services.EmailSmtpSettingsService.build_connection") as build:
        result = EmailCampaignSendService().send_due_entries()
    assert result["cancelled"] == 1
    assert EmailCampaignQueueEntry.objects.get().status == EmailCampaignQueueEntry.Status.CANCELLED
    build.assert_not_called()


@pytest.mark.django_db
def test_test_queue_checks_shopware_before_smtp(test_group, render, settings):
    campaign, group, recipient = test_group
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
    shopware = MagicMock()
    shopware.request_post.return_value = {
        "data": [{"id": recipient.shopware_id, "status": "optOut", "email": recipient.email}]
    }
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService", return_value=shopware), patch(
        "emails.services.EmailSmtpSettingsService.build_connection"
    ) as build:
        result = EmailCampaignSendService().send_due_entries()
    assert result["cancelled"] == 1
    assert EmailCampaignQueueEntry.objects.get().status == EmailCampaignQueueEntry.Status.CANCELLED
    build.assert_not_called()


@pytest.mark.django_db
def test_test_group_skips_inactive_and_duplicate_addresses(test_group, render):
    campaign, group, recipient = test_group
    duplicate = NewsletterRecipient.objects.create(
        shopware_id="person-2", email="ONE@example.com", status=NewsletterRecipient.Status.OPT_IN
    )
    inactive = NewsletterRecipient.objects.create(
        shopware_id="person-3", email="inactive@example.com", status=NewsletterRecipient.Status.OPT_OUT
    )
    group.members.add(duplicate, inactive)
    result = EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
    assert result == {"queued": 1, "skipped": 2, "failed": 0}
    assert EmailCampaignQueueEntry.objects.count() == 1
    assert EmailCampaignQueueEntry.objects.get().recipient == recipient


@pytest.mark.django_db
def test_test_group_can_be_run_again_with_new_batch(test_group, render):
    campaign, group, _ = test_group
    service = EmailCampaignTestQueueService()
    service.queue_group(campaign=campaign, group=group)
    service.queue_group(campaign=campaign, group=group)
    assert EmailCampaignQueueEntry.objects.count() == 2
    assert EmailCampaignQueueEntry.objects.values_list("test_batch", flat=True).distinct().count() == 2


@pytest.mark.django_db
def test_test_queue_does_not_replace_later_series_entry(test_group, render):
    from emails.services import EmailCampaignQueueService

    campaign, group, recipient = test_group
    EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
    recipient.selected_email_campaign = campaign
    recipient.save(update_fields=["selected_email_campaign"])
    series_entry = EmailCampaignQueueService().queue_recipient_campaign(recipient)
    assert series_entry.test_batch is None
    assert EmailCampaignQueueEntry.objects.filter(campaign=campaign, recipient=recipient).count() == 2


@pytest.mark.django_db
def test_test_group_rejects_oversize_before_queue(test_group, render):
    campaign, group, _ = test_group
    group.members.add(*[
        NewsletterRecipient.objects.create(
            shopware_id=f"person-{i}", email=f"person-{i}@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
        )
        for i in range(2, 23)
    ])
    with pytest.raises(ValueError, match="höchstens 20"):
        EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
    assert EmailCampaignQueueEntry.objects.count() == 0


@pytest.mark.django_db
def test_series_entry_is_blocked_even_when_smtp_active(test_group, settings):
    _, _, recipient = test_group
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    campaign = EmailCampaign.objects.create(
        internal_title="Serie", subject="Live", status=EmailCampaign.Status.READY,
        send_at=timezone.now() - timedelta(minutes=1),
    )
    recipient.selected_email_campaign = campaign
    recipient.save(update_fields=["selected_email_campaign"])
    entry = EmailCampaignQueueEntry.objects.create(
        campaign=campaign, recipient=recipient, email=recipient.email, subject="Live",
        rendered_html="<p>live</p>", rendered_text="live",
    )
    EmailSmtpSettings.objects.filter(pk=1).update(is_active=True)
    with patch("emails.services.EmailSmtpSettingsService.build_connection") as build:
        result = EmailCampaignSendService().send_due_entries()
    entry.refresh_from_db()
    assert result["sent"] == 0
    assert entry.status == EmailCampaignQueueEntry.Status.QUEUED
    build.assert_not_called()
