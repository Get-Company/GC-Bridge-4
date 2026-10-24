from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from emails.models import EmailCampaign, EmailCampaignQueueEntry, EmailSmtpSettings
from emails.services import EmailCampaignSendService, EmailCampaignTestQueueService
from newsletter.models import NewsletterRecipient


@pytest.fixture
def marked_contact():
    campaign = EmailCampaign.objects.create(
        internal_title="November", subject="Hybride Arbeitswelt", status=EmailCampaign.Status.DRAFT
    )
    recipient = NewsletterRecipient.objects.create(
        shopware_id="person-1", email="one@example.com", status=NewsletterRecipient.Status.OPT_IN,
        is_test_recipient=True,
    )
    EmailSmtpSettings.objects.create(
        is_active=False, host="smtp.example.com", sender_email="newsletter@example.com"
    )
    return campaign, recipient


@pytest.fixture
def render():
    with patch("emails.services.render_campaign_mjml", return_value="<mjml>draft</mjml>"), patch(
        "emails.services.compile_mjml_to_html", return_value="<p>draft</p>"
    ), patch("emails.services.html_to_plain_text", return_value="draft"):
        yield


def queue_marked(campaign):
    return EmailCampaignTestQueueService().queue_marked(
        campaign=campaign,
        expected_fingerprint=EmailCampaignTestQueueService.selection_fingerprint(campaign),
    )


@pytest.mark.django_db
def test_marked_contact_uses_same_queue_and_worker_without_enabling_series(marked_contact, render, settings):
    campaign, recipient = marked_contact
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    queued = queue_marked(campaign)
    entry = EmailCampaignQueueEntry.objects.get()
    assert queued == {"queued": 1, "skipped": 0, "failed": 0}
    assert entry.test_batch is not None
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
def test_unmarked_contact_is_cancelled_before_smtp(marked_contact, render, settings):
    campaign, recipient = marked_contact
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    queue_marked(campaign)
    recipient.is_test_recipient = False
    recipient.save(update_fields=["is_test_recipient"])
    with patch("emails.services.EmailSmtpSettingsService.build_connection") as build:
        result = EmailCampaignSendService().send_due_entries()
    assert result["cancelled"] == 1
    assert EmailCampaignQueueEntry.objects.get().status == EmailCampaignQueueEntry.Status.CANCELLED
    build.assert_not_called()


@pytest.mark.django_db
def test_test_queue_checks_shopware_before_smtp(marked_contact, render, settings):
    campaign, recipient = marked_contact
    settings.NEWSLETTER_SERIES_SEND_ENABLED = False
    queue_marked(campaign)
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
def test_only_marked_contacts_queue_and_duplicates_are_skipped(marked_contact, render):
    campaign, recipient = marked_contact
    duplicate = NewsletterRecipient.objects.create(
        shopware_id="person-2", email="ONE@example.com", status=NewsletterRecipient.Status.OPT_IN,
        is_test_recipient=True,
    )
    NewsletterRecipient.objects.create(
        shopware_id="person-3", email="ordinary@example.com", status=NewsletterRecipient.Status.OPT_IN,
    )
    result = queue_marked(campaign)
    assert result == {"queued": 1, "skipped": 1, "failed": 0}
    assert EmailCampaignQueueEntry.objects.get().recipient == recipient
    assert duplicate.is_test_recipient


@pytest.mark.django_db
def test_changed_selection_requires_new_confirmation(marked_contact, render):
    campaign, recipient = marked_contact
    fingerprint = EmailCampaignTestQueueService.selection_fingerprint(campaign)
    recipient.is_test_recipient = False
    recipient.save(update_fields=["is_test_recipient"])
    with pytest.raises(ValueError, match="geändert"):
        EmailCampaignTestQueueService().queue_marked(
            campaign=campaign, expected_fingerprint=fingerprint
        )
    assert EmailCampaignQueueEntry.objects.count() == 0


@pytest.mark.django_db
def test_marked_contacts_can_be_tested_again_and_do_not_replace_series(marked_contact, render):
    from emails.services import EmailCampaignQueueService

    campaign, recipient = marked_contact
    queue_marked(campaign)
    queue_marked(campaign)
    recipient.selected_email_campaign = campaign
    recipient.save(update_fields=["selected_email_campaign"])
    series_entry = EmailCampaignQueueService().queue_recipient_campaign(recipient)
    assert series_entry.test_batch is None
    assert EmailCampaignQueueEntry.objects.filter(campaign=campaign, recipient=recipient).count() == 3


@pytest.mark.django_db
def test_too_many_marked_contacts_are_rejected_before_queue(marked_contact, render):
    campaign, _ = marked_contact
    for i in range(2, 23):
        NewsletterRecipient.objects.create(
            shopware_id=f"person-{i}", email=f"person-{i}@example.com",
            status=NewsletterRecipient.Status.OPT_IN, is_test_recipient=True,
        )
    with pytest.raises(ValueError, match="Höchstens 20"):
        queue_marked(campaign)
    assert EmailCampaignQueueEntry.objects.count() == 0


@pytest.mark.django_db
def test_series_entry_stays_blocked_even_when_smtp_active(marked_contact, settings):
    _, recipient = marked_contact
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
