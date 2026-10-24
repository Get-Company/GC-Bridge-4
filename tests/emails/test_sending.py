from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone


@pytest.fixture
def delivery():
    from emails.models import EmailCampaign, EmailCampaignQueueEntry, EmailSmtpSettings
    from newsletter.models import NewsletterRecipient

    campaign = EmailCampaign.objects.create(
        internal_title="Newsletter",
        subject="Test Newsletter",
        status=EmailCampaign.Status.READY,
        send_at=timezone.now() - timedelta(minutes=1),
    )
    recipient = NewsletterRecipient.objects.create(
        shopware_id="recipient-1",
        email="one@example.com",
        status=NewsletterRecipient.Status.OPT_IN,
        selected_email_campaign=campaign,
    )
    entry = EmailCampaignQueueEntry.objects.create(
        campaign=campaign,
        recipient=recipient,
        email=recipient.email,
        subject=campaign.subject,
        rendered_html="<p>Newsletter</p>",
        rendered_text="Newsletter",
    )
    EmailSmtpSettings.objects.create(
        is_active=True,
        host="smtp.example.com",
        sender_email="newsletter@example.com",
    )
    return campaign, recipient, entry


def remote_recipient(status="optIn", email="one@example.com"):
    return {"data": [{"id": "recipient-1", "status": status, "email": email}]}


@pytest.mark.django_db
def test_sends_one_personalized_message_and_never_repeats(delivery):
    from emails.models import EmailCampaignQueueEntry
    from emails.services import EmailCampaignSendService

    _, _, entry = delivery
    connection = MagicMock()
    connection.send_messages.return_value = 1
    shopware = MagicMock()
    shopware.request_post.return_value = remote_recipient()
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService", return_value=shopware), patch(
        "emails.services.EmailSmtpSettingsService.build_connection", return_value=connection
    ):
        first = EmailCampaignSendService().send_due_entries(batch_size=10)
        second = EmailCampaignSendService().send_due_entries(batch_size=10)

    entry.refresh_from_db()
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert entry.status == EmailCampaignQueueEntry.Status.SENT
    assert entry.attempt_count == 1
    assert entry.sent_at is not None
    connection.send_messages.assert_called_once()
    message = connection.send_messages.call_args.args[0][0]
    assert message.to == ["one@example.com"]
    assert message.subject == "Test Newsletter"
    assert message.extra_headers["List-Unsubscribe"].startswith("<https://www.classei-shop.com/Newsletter/#")


@pytest.mark.django_db
def test_live_shopware_opt_out_cancels_before_smtp(delivery):
    from emails.models import EmailCampaignQueueEntry
    from emails.services import EmailCampaignSendService

    _, _, entry = delivery
    shopware = MagicMock()
    shopware.request_post.return_value = remote_recipient(status="optOut")
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService", return_value=shopware), patch(
        "emails.services.EmailSmtpSettingsService.build_connection"
    ) as build_connection:
        summary = EmailCampaignSendService().send_due_entries()

    entry.refresh_from_db()
    assert summary["cancelled"] == 1
    assert entry.status == EmailCampaignQueueEntry.Status.CANCELLED
    build_connection.assert_not_called()


@pytest.mark.django_db
def test_shopware_outage_retries_before_smtp(delivery):
    from emails.models import EmailCampaignQueueEntry
    from emails.services import EmailCampaignSendService

    _, _, entry = delivery
    shopware = MagicMock()
    shopware.request_post.side_effect = TimeoutError("Shopware not responding")
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService", return_value=shopware), patch(
        "emails.services.EmailSmtpSettingsService.build_connection"
    ) as build_connection:
        summary = EmailCampaignSendService().send_due_entries()

    entry.refresh_from_db()
    assert summary["retry"] == 1
    assert entry.status == EmailCampaignQueueEntry.Status.QUEUED
    assert entry.next_attempt_at > timezone.now()
    build_connection.assert_not_called()


@pytest.mark.django_db
def test_smtp_error_remains_failed_without_automatic_duplicate(delivery):
    from emails.models import EmailCampaignQueueEntry
    from emails.services import EmailCampaignSendService

    _, _, entry = delivery
    connection = MagicMock()
    connection.send_messages.side_effect = TimeoutError("uncertain SMTP acknowledgement")
    shopware = MagicMock()
    shopware.request_post.return_value = remote_recipient()
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService", return_value=shopware), patch(
        "emails.services.EmailSmtpSettingsService.build_connection", return_value=connection
    ):
        first = EmailCampaignSendService().send_due_entries()
        second = EmailCampaignSendService().send_due_entries()

    entry.refresh_from_db()
    assert first["failed"] == 1
    assert second["failed"] == 0
    assert entry.status == EmailCampaignQueueEntry.Status.FAILED
    assert connection.send_messages.call_count == 1


@pytest.mark.django_db
def test_inactive_smtp_and_future_campaign_do_not_send(delivery):
    from emails.models import EmailSmtpSettings
    from emails.services import EmailCampaignSendService

    campaign, _, _ = delivery
    EmailSmtpSettings.objects.filter(pk=1).update(is_active=False)
    assert EmailCampaignSendService().send_due_entries()["disabled"] == 1
    EmailSmtpSettings.objects.filter(pk=1).update(is_active=True)
    campaign.send_at = timezone.now() + timedelta(hours=1)
    campaign.save(update_fields=("send_at",))
    with patch("newsletter.services.recipient_sync.NewsletterRecipientShopwareService") as service:
        assert EmailCampaignSendService().send_due_entries()["sent"] == 0
    service.return_value.request_post.assert_not_called()


@pytest.mark.django_db
@patch("emails.services.compile_mjml_to_html", return_value="<p>new</p>")
@patch("emails.services.render_campaign_mjml", return_value="<mjml>new</mjml>")
def test_queue_does_not_reset_sent_entry(render_mjml, compile_html, delivery):
    from emails.models import EmailCampaignQueueEntry
    from emails.services import EmailCampaignQueueService

    _, recipient, entry = delivery
    entry.status = EmailCampaignQueueEntry.Status.SENT
    entry.sent_at = timezone.now()
    entry.save(update_fields=("status", "sent_at"))

    queued = EmailCampaignQueueService().queue_recipient_campaign(recipient)

    assert queued.pk == entry.pk
    assert queued.status == EmailCampaignQueueEntry.Status.SENT
    assert EmailCampaignQueueEntry.objects.count() == 1
    render_mjml.assert_not_called()
    compile_html.assert_not_called()
