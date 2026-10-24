from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse
import pytest

from emails.models import EmailCampaign, EmailCampaignQueueEntry
from emails.services import EmailCampaignTestQueueService
from newsletter.models import NewsletterRecipient


def _recipient(number, *, marked=False):
    return NewsletterRecipient.objects.create(
        shopware_id=f"shopware-{number}",
        email=f"person-{number}@example.com",
        status=NewsletterRecipient.Status.OPT_IN,
        is_test_recipient=marked,
    )


def _action_request(campaign, *, confirm=True, fingerprint=None):
    data = {
        "_form_submitted": "True",
        "selection_fingerprint": fingerprint or EmailCampaignTestQueueService.selection_fingerprint(campaign),
    }
    if confirm:
        data["confirm"] = "on"
    request = RequestFactory().post("/admin/emails/emailcampaign/", data)
    user_model = get_user_model()
    request.user = user_model.objects.filter(username="test-admin").first()
    if request.user is None:
        request.user = user_model.objects.create_superuser(
            username="test-admin", email="test-admin@example.com", password="test-password"
        )
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_campaign_action_queues_marked_contacts_only_after_confirmation():
    campaign = EmailCampaign.objects.create(internal_title="Hybride Arbeitswelt", status="draft")
    marked = _recipient(1, marked=True)
    _recipient(2)
    model_admin = admin.site._registry[EmailCampaign]

    with patch("emails.services.EmailCampaignTestQueueService.queue_marked") as queue, patch(
        "emails.tasks.send_due_campaign_queue.delay"
    ) as trigger:
        queue.return_value = {"queued": 1, "skipped": 0, "failed": 0}
        unconfirmed = _action_request(campaign, confirm=False)
        response = model_admin.queue_marked_test_recipients_detail(unconfirmed, object_id=str(campaign.pk))
        assert response.status_code == 200
        queue.assert_not_called()
        trigger.assert_not_called()

        confirmed = _action_request(campaign)
        response = model_admin.queue_marked_test_recipients_detail(confirmed, object_id=str(campaign.pk))
        assert response.status_code == 302
        queue.assert_called_once_with(
            campaign=campaign,
            expected_fingerprint=EmailCampaignTestQueueService.selection_fingerprint(campaign),
        )
        trigger.assert_called_once_with()
        assert "1 eingereiht" in " ".join(str(item) for item in confirmed._messages)

    marked.refresh_from_db()
    assert marked.selected_email_campaign is None
    assert EmailCampaignQueueEntry.objects.count() == 0


@pytest.mark.django_db
def test_campaign_action_rejects_changed_flags_and_ready_campaign():
    campaign = EmailCampaign.objects.create(internal_title="Entwurf", status="draft")
    recipient = _recipient(1, marked=True)
    fingerprint = EmailCampaignTestQueueService.selection_fingerprint(campaign)
    recipient.is_test_recipient = False
    recipient.save(update_fields=["is_test_recipient"])
    model_admin = admin.site._registry[EmailCampaign]

    with patch("emails.services.EmailCampaignTestQueueService.queue_marked") as queue:
        stale_request = _action_request(campaign, fingerprint=fingerprint)
        response = model_admin.queue_marked_test_recipients_detail(stale_request, object_id=str(campaign.pk))
        assert response.status_code == 200
        queue.assert_not_called()

        recipient.is_test_recipient = True
        recipient.save(update_fields=["is_test_recipient"])
        campaign.status = EmailCampaign.Status.READY
        campaign.save(update_fields=["status"])
        ready_request = _action_request(campaign)
        response = model_admin.queue_marked_test_recipients_detail(ready_request, object_id=str(campaign.pk))
        assert response.status_code == 200
        queue.assert_not_called()


@pytest.mark.django_db
def test_recipient_admin_exposes_editable_flag_and_filter(client, settings):
    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    marked = _recipient(1, marked=True)
    ordinary = _recipient(2)
    user = get_user_model().objects.create_superuser(
        username="test-admin", email="test-admin@example.com", password="test-password"
    )
    client.force_login(user)
    admin_model = admin.site._registry[NewsletterRecipient]
    assert "is_test_recipient" in admin_model.list_editable
    assert ("is_test_recipient", admin_model.list_filter[1][1]) in admin_model.list_filter

    list_page = client.get(reverse("admin:newsletter_newsletterrecipient_changelist"))
    detail_page = client.get(reverse("admin:newsletter_newsletterrecipient_change", args=(marked.pk,)))
    assert list_page.status_code == 200
    assert detail_page.status_code == 200
    assert b'name="form-0-is_test_recipient"' in list_page.content
    assert b'name="is_test_recipient"' in detail_page.content
    filtered = client.get(
        reverse("admin:newsletter_newsletterrecipient_changelist"),
        {"is_test_recipient__exact": "1"},
    )
    assert filtered.status_code == 200
    assert marked.email.encode() in filtered.content
    assert ordinary.email.encode() not in filtered.content
    assert ordinary.is_test_recipient is False


@pytest.mark.django_db
def test_shopware_sync_keeps_local_test_flag():
    from newsletter.services import NewsletterRecipientSyncService

    marked = _recipient(1, marked=True)
    NewsletterRecipientSyncService().upsert_from_shopware(
        {"id": marked.shopware_id, "email": marked.email, "status": "optIn"},
        customer_service=None,
    )
    marked.refresh_from_db()
    assert marked.is_test_recipient is True


@pytest.mark.django_db
def test_admin_list_can_mark_contact_as_test_recipient(client, settings):
    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    recipient = _recipient(1)
    user = get_user_model().objects.create_superuser(
        username="test-admin", email="test-admin@example.com", password="test-password"
    )
    client.force_login(user)
    response = client.post(
        reverse("admin:newsletter_newsletterrecipient_changelist"),
        {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(recipient.pk),
            "form-0-is_test_recipient": "on",
            "_save": "Speichern",
        },
    )
    assert response.status_code == 302
    recipient.refresh_from_db()
    assert recipient.is_test_recipient is True


@pytest.mark.django_db
def test_campaign_admin_exposes_test_send_action(client, settings):
    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    campaign = EmailCampaign.objects.create(internal_title="Hybride Arbeitswelt", status="draft")
    _recipient(1, marked=True)
    user = get_user_model().objects.create_superuser(
        username="test-admin", email="test-admin@example.com", password="test-password"
    )
    client.force_login(user)
    page = client.get(reverse("admin:emails_emailcampaign_change", args=(campaign.pk,)))
    assert page.status_code == 200
    assert "Test-E-Mails an markierte Empfänger einreihen" in page.content.decode()
