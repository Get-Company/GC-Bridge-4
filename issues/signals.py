from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


ISSUE_ALERT_PENDING_SESSION_KEY = "issues_alert_pending"


@receiver(user_logged_in, dispatch_uid="issues.mark_issue_alert_pending")
def mark_issue_alert_pending(sender, request, user, **kwargs):
    """Request issue alerts once on the first admin page after a real login."""

    if request is not None and hasattr(request, "session"):
        request.session[ISSUE_ALERT_PENDING_SESSION_KEY] = True
