from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.management import call_command

from newsletter.links import unsubscribe_url


def test_personal_link_uses_a_fragment_and_preserves_special_characters(settings):
    settings.NEWSLETTER_MANAGEMENT_URL = "https://www.classei-shop.com/Newsletter/"
    parts = urlsplit(unsubscribe_url("name+news&more@example.com"))
    assert parts.query == ""
    assert parts.path == "/Newsletter/"
    assert parse_qs(parts.fragment) == {"option": ["unsubscribe"], "email": ["name+news&more@example.com"]}


def test_anonymous_preview_still_links_to_the_management_form():
    assert parse_qs(urlsplit(unsubscribe_url()).fragment)["option"] == ["unsubscribe"]


def test_invalid_management_url_is_rejected(settings):
    settings.NEWSLETTER_MANAGEMENT_URL = "javascript:alert(1)"
    with pytest.raises(ValueError):
        unsubscribe_url("test@example.com")


@pytest.mark.django_db
def test_subscription_changes_cancel_only_waiting_emails_and_allow_resubscription():
    from emails.models import EmailCampaign, EmailCampaignQueueEntry
    from newsletter.models import NewsletterRecipient
    from newsletter.services import NewsletterRecipientSyncService

    service = NewsletterRecipientSyncService()
    lookup = MagicMock()
    lookup.get_by_email.return_value = {"data": [], "total": 0}
    payload = {"id": "test-newsletter", "email": "newsletter@example.com", "status": "optIn"}
    recipient, _ = service.upsert_from_shopware(payload, customer_service=lookup)
    campaign = EmailCampaign.objects.create(internal_title="Newsletter test")
    waiting = EmailCampaignQueueEntry.objects.create(campaign=campaign, recipient=recipient, email=recipient.email)
    sent = EmailCampaignQueueEntry.objects.create(
        campaign=campaign, recipient=recipient, email=recipient.email,
        test_batch=uuid4(), status="sent",
    )
    service.upsert_from_shopware(payload | {"status": "optOut"}, customer_service=lookup)
    recipient.refresh_from_db()
    waiting.refresh_from_db()
    sent.refresh_from_db()
    assert recipient.status == "optOut"
    assert not recipient.is_active_status
    assert waiting.status == "cancelled"
    assert sent.status == "sent"
    service.upsert_from_shopware(payload, customer_service=lookup)
    recipient.refresh_from_db()
    waiting.refresh_from_db()
    assert recipient.is_active_status
    assert waiting.status == "cancelled"


@pytest.mark.django_db
def test_deleted_recipient_is_marked_missing_and_pending_message_cancelled():
    from emails.models import EmailCampaign, EmailCampaignQueueEntry
    from newsletter.models import NewsletterRecipient
    from newsletter.services import NewsletterRecipientSyncService

    recipient = NewsletterRecipient.objects.create(shopware_id="gone", email="gone@example.com", status="optIn")
    campaign = EmailCampaign.objects.create(internal_title="Newsletter test")
    waiting = EmailCampaignQueueEntry.objects.create(campaign=campaign, recipient=recipient, email=recipient.email)
    assert NewsletterRecipientSyncService._mark_missing(set()) == 1
    recipient.refresh_from_db()
    waiting.refresh_from_db()
    assert not recipient.is_present_in_shopware
    assert waiting.status == "cancelled"


@pytest.mark.django_db
def test_failed_import_of_present_recipient_does_not_mark_it_as_deleted():
    from newsletter.models import NewsletterRecipient
    from newsletter.services import NewsletterRecipientSyncService

    recipient = NewsletterRecipient.objects.create(shopware_id="present", email="test@example.com", status="optIn")
    remote = MagicMock()
    remote.list_recipients.return_value = {"data": [{"id": "present"}], "total": 1}
    summary = NewsletterRecipientSyncService().sync_from_shopware(
        shopware_service=remote, customer_service=MagicMock(), mark_missing=True,
    )
    recipient.refresh_from_db()
    assert summary["failed"] == 1
    assert summary["marked_missing"] == 0
    assert recipient.is_present_in_shopware


@pytest.mark.django_db
def test_daily_schedule_updates_existing_task_without_duplicates():
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    weekly = CrontabSchedule.objects.create(minute="0", hour="2", day_of_week="1", timezone="Europe/Berlin")
    task = PeriodicTask.objects.create(name="Newsletter weekly", task="newsletter.shopware_sync_recipients", crontab=weekly)
    call_command("configure_newsletter_sync")
    call_command("configure_newsletter_sync")
    task.refresh_from_db()
    assert PeriodicTask.objects.filter(task=task.task).count() == 1
    assert task.enabled
    assert task.crontab.hour == "2" and task.crontab.minute == "0"
    assert task.crontab.day_of_week == "*"
    assert str(task.crontab.timezone) == "Europe/Berlin"
    assert '"mark_missing": true' in task.kwargs


def test_footer_renders_personal_link_and_normalizes_legacy_tags():
    from emails.mjml import _jinja_env, normalize_legacy_recipient_placeholders, recipient_context
    context = recipient_context(SimpleNamespace(customer=None, email="test+newsletter@example.com"))
    rendered = _jinja_env.from_string(normalize_legacy_recipient_placeholders(
        '<p>{modify}hier{/modify}</p><a href="{modify}">abmelden</a>'
    )).render(context)
    assert "{modify}" not in rendered
    assert "test%2Bnewsletter%40example.com" in rendered
    assert '<a href="https://' in rendered
