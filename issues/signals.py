from django.contrib.auth.signals import user_logged_in
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from issues.models import Issue, IssueMessage, IssueNotification


ISSUE_ALERT_PENDING_SESSION_KEY = "issues_alert_pending"


@receiver(user_logged_in, dispatch_uid="issues.mark_issue_alert_pending")
def mark_issue_alert_pending(sender, request, user, **kwargs):
    """Request issue alerts once on the first admin page after a real login."""

    if request is not None and hasattr(request, "session"):
        request.session[ISSUE_ALERT_PENDING_SESSION_KEY] = True


def notify_issue_participants(issue, kind, actor=None, detail=""):
    participant_ids = {issue.reported_by_id, issue.assigned_to_id}
    participant_ids.update(issue.messages.values_list("author_id", flat=True))
    participant_ids.update(issue.notifications.exclude(actor__isnull=True).values_list("actor_id", flat=True))
    participant_ids.discard(None)
    if actor is not None:
        participant_ids.discard(actor.pk)
    users = get_user_model().objects.filter(pk__in=participant_ids, is_active=True, is_staff=True)
    IssueNotification.objects.bulk_create(
        IssueNotification(issue=issue, user=user, actor=actor, kind=kind, detail=detail)
        for user in users
    )


@receiver(pre_save, sender=Issue, dispatch_uid="issues.remember_previous_status")
def remember_previous_status(sender, instance, **kwargs):
    instance._previous_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk else None
    )


@receiver(post_save, sender=Issue, dispatch_uid="issues.notify_status_change")
def notify_status_change(sender, instance, created, **kwargs):
    previous = getattr(instance, "_previous_status", None)
    if created or previous is None or previous == instance.status:
        return
    actor = getattr(instance, "_issue_notification_actor", None)
    notify_issue_participants(
        instance,
        IssueNotification.Kind.STATUS,
        actor=actor,
        detail=instance.get_status_display(),
    )


@receiver(post_save, sender=IssueMessage, dispatch_uid="issues.notify_new_message")
def notify_new_message(sender, instance, created, **kwargs):
    if created:
        notify_issue_participants(
            instance.issue,
            IssueNotification.Kind.MESSAGE,
            actor=instance.author,
            detail=instance.body[:255],
        )
