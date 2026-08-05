from __future__ import annotations

from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from issues.models import Issue, IssueAlertState
from issues.signals import ISSUE_ALERT_PENDING_SESSION_KEY


def issue_alerts(request):
    """Expose newly created issues once after an authenticated staff login."""

    session = getattr(request, "session", None)
    if (
        request is None
        or not getattr(request, "user", None)
        or not request.user.is_authenticated
        or not request.user.is_staff
        or session is None
        or not session.pop(ISSUE_ALERT_PENDING_SESSION_KEY, False)
    ):
        return {}

    try:
        state, created = IssueAlertState.objects.get_or_create(user=request.user)
        if created or state.last_notified_at is None:
            state.last_notified_at = timezone.now()
            state.save(update_fields=("last_notified_at", "updated_at"))
            return {"issue_alerts": []}

        issues = list(
            Issue.objects.filter(created_at__gt=state.last_notified_at)
            .only("id", "title", "status", "created_at")
            .order_by("created_at", "id")
        )
        if not issues:
            return {"issue_alerts": []}

        state.last_notified_at = issues[-1].created_at
        state.save(update_fields=("last_notified_at", "updated_at"))
    except DatabaseError:
        return {"issue_alerts": []}

    terminal_statuses = {Issue.Status.RESOLVED, Issue.Status.CLOSED}
    return {
        "issue_alerts": [
            {
                "title": issue.title,
                "url": reverse(
                    "admin:issues_archivedissue_change"
                    if issue.status in terminal_statuses
                    else "admin:issues_issue_change",
                    args=(issue.pk,),
                ),
            }
            for issue in issues
        ]
    }
