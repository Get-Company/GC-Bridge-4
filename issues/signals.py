from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_migrate
from django.dispatch import receiver


ISSUE_ALERT_PENDING_SESSION_KEY = "issues_alert_pending"


@receiver(user_logged_in, dispatch_uid="issues.mark_issue_alert_pending")
def mark_issue_alert_pending(sender, request, user, **kwargs):
    """Request issue alerts once on the first admin page after a real login."""

    if request is not None and hasattr(request, "session"):
        request.session[ISSUE_ALERT_PENDING_SESSION_KEY] = True


@receiver(post_migrate, dispatch_uid="issues.backfill_initial_messages")
def backfill_initial_messages(sender, apps, using, **kwargs):
    """Turn existing Issue.error_text values into authored first messages once."""
    if sender.label != "issues":
        return
    try:
        issue_model = apps.get_model("issues", "Issue")
        message_model = apps.get_model("issues", "IssueMessage")
    except LookupError:
        return
    if "is_initial" not in {field.name for field in message_model._meta.local_fields}:
        return

    existing = message_model.objects.using(using).filter(is_initial=True).values("issue_id")
    issues = (
        issue_model.objects.using(using)
        .exclude(error_text="")
        .exclude(pk__in=existing)
        .only("id", "reported_by_id", "error_text", "created_at")
    )
    for issue in issues:
        message, created = message_model.objects.using(using).get_or_create(
            issue_id=issue.pk,
            is_initial=True,
            defaults={"author_id": issue.reported_by_id, "text": issue.error_text},
        )
        if created:
            message_model.objects.using(using).filter(pk=message.pk).update(
                created_at=issue.created_at
            )
