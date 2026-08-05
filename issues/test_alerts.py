from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.utils import timezone

from issues.context_processors import issue_alerts
from issues.models import Issue, IssueAlertState
from issues.signals import ISSUE_ALERT_PENDING_SESSION_KEY


class IssueAlertsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            id=1,
            username="issue-alert-user",
            password="test-password",
            is_staff=True,
        )
        self.request_factory = RequestFactory()

    def _request(self):
        request = self.request_factory.get("/")
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request.user = self.user
        request.session[ISSUE_ALERT_PENDING_SESSION_KEY] = True
        return request

    def test_first_login_sets_the_alert_cursor_without_historical_alerts(self):
        Issue.objects.create(title="Bereits vorhandenes Issue", assigned_to=self.user)

        context = issue_alerts(self._request())

        self.assertEqual(context["issue_alerts"], [])
        self.assertIsNotNone(IssueAlertState.objects.get(user=self.user).last_notified_at)

    def test_next_login_alerts_new_issues_exactly_once(self):
        state = IssueAlertState.objects.create(user=self.user, last_notified_at=timezone.now())
        issue = Issue.objects.create(title="Neues Issue", assigned_to=self.user)

        context = issue_alerts(self._request())

        self.assertEqual([alert["title"] for alert in context["issue_alerts"]], [issue.title])
        self.assertEqual(IssueAlertState.objects.get(pk=state.pk).last_notified_at, issue.created_at)
        self.assertEqual(issue_alerts(self._request())["issue_alerts"], [])
