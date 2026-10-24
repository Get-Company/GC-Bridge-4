from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse
import pytest

from emails.models import EmailCampaign, EmailCampaignQueueEntry
from newsletter.admin import RecipientGroupFilter, _group_test_selection_fingerprint
from newsletter.models import NewsletterRecipient, NewsletterRecipientGroup


def _recipient(number, *, status=NewsletterRecipient.Status.OPT_IN, present=True):
    return NewsletterRecipient.objects.create(
        shopware_id=f"shopware-{number}",
        email=f"person-{number}@example.com",
        status=status,
        is_present_in_shopware=present,
    )


def _request_for_action(group, *, confirm=True, fingerprint=None):
    data = {
        "_form_submitted": "True",
        "selection_fingerprint": fingerprint or _group_test_selection_fingerprint(group),
    }
    if confirm:
        data["confirm"] = "on"
    request = RequestFactory().post("/admin/newsletter/", data)
    user_model = get_user_model()
    request.user = user_model.objects.filter(username="pilot-admin").first()
    if request.user is None:
        request.user = user_model.objects.create_superuser(
            username="pilot-admin", email="pilot-admin@example.com", password="test-password"
        )
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_group_test_action_queues_existing_draft_only_after_confirmation():
    campaign = EmailCampaign.objects.create(internal_title="Hybride Arbeitswelt", status="draft")
    group = NewsletterRecipientGroup.objects.create(
        name="Newsletter Pilot – nur Florian", test_email_campaign=campaign
    )
    member = _recipient(1)
    group.members.add(member)
    model_admin = admin.site._registry[NewsletterRecipientGroup]

    with patch("emails.services.EmailCampaignTestQueueService.queue_group") as queue, patch(
        "emails.tasks.send_due_campaign_queue.delay"
    ) as trigger:
        queue.return_value = {"queued": 1, "skipped": 0, "failed": 0, "errors": []}
        unconfirmed = _request_for_action(group, confirm=False)
        response = model_admin.queue_group_test_detail(unconfirmed, object_id=str(group.pk))
        assert response.status_code == 200
        queue.assert_not_called()
        trigger.assert_not_called()

        confirmed = _request_for_action(group)
        response = model_admin.queue_group_test_detail(confirmed, object_id=str(group.pk))
        assert response.status_code == 302
        queue.assert_called_once_with(campaign=campaign, group=group)
        trigger.assert_called_once_with()
        assert "1 eingereiht" in " ".join(str(item) for item in confirmed._messages)

    member.refresh_from_db()
    assert member.selected_email_campaign is None
    assert EmailCampaignQueueEntry.objects.count() == 0


@pytest.mark.django_db
def test_group_test_action_rejects_changed_membership_and_ready_campaign():
    campaign = EmailCampaign.objects.create(internal_title="Entwurf", status="draft")
    group = NewsletterRecipientGroup.objects.create(name="Pilot", test_email_campaign=campaign)
    group.members.add(_recipient(1))
    fingerprint = _group_test_selection_fingerprint(group)
    group.members.add(_recipient(2))
    model_admin = admin.site._registry[NewsletterRecipientGroup]

    with patch("emails.services.EmailCampaignTestQueueService.queue_group") as queue:
        stale_request = _request_for_action(group, fingerprint=fingerprint)
        response = model_admin.queue_group_test_detail(stale_request, object_id=str(group.pk))
        assert response.status_code == 200
        queue.assert_not_called()

        campaign.status = EmailCampaign.Status.READY
        campaign.save(update_fields=["status"])
        ready_request = _request_for_action(group)
        response = model_admin.queue_group_test_detail(ready_request, object_id=str(group.pk))
        assert response.status_code == 302
        queue.assert_not_called()


@pytest.mark.django_db
def test_group_is_visible_and_filterable_in_recipient_admin():
    group = NewsletterRecipientGroup.objects.create(name="Newsletter Pilot – nur Florian")
    member = _recipient(1)
    other = _recipient(2)
    group.members.add(member)
    model_admin = admin.site._registry[NewsletterRecipient]
    request = RequestFactory().get(
        reverse("admin:newsletter_newsletterrecipient_changelist"),
        {"recipient_group": str(group.pk)},
    )
    group_filter = RecipientGroupFilter(
        request, {"recipient_group": str(group.pk)}, NewsletterRecipient, model_admin
    )

    assert list(group_filter.queryset(request, NewsletterRecipient.objects.all())) == [member]
    assert "Newsletter Pilot" in str(model_admin.recipient_groups_display(member))
    assert other not in group_filter.queryset(request, NewsletterRecipient.objects.all())


@pytest.mark.django_db
def test_group_admin_exposes_member_picker_and_test_queue_action(client, settings):
    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    group = NewsletterRecipientGroup.objects.create(name="Newsletter Pilot – nur Florian")
    user = get_user_model().objects.create_superuser(
        username="pilot-admin", email="pilot-admin@example.com", password="test-password"
    )
    client.force_login(user)

    add_page = client.get(reverse("admin:newsletter_newsletterrecipientgroup_add"))
    change_page = client.get(
        reverse("admin:newsletter_newsletterrecipientgroup_change", args=(group.pk,))
    )

    assert add_page.status_code == 200
    assert b'name="members"' in add_page.content
    assert change_page.status_code == 200
    assert "Test-E-Mails des Kreises einreihen" in change_page.content.decode()
