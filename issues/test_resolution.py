from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from issues.admin import IssueAdmin
from issues.models import Issue


class IssueResolutionTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            id=1,
            username="issue-resolution-user",
            password="test-password",
            is_staff=True,
        )

    def test_terminal_issue_requires_a_solution_documentation(self):
        issue = Issue(
            title="Abzuschließendes Issue",
            status=Issue.Status.RESOLVED,
            assigned_to=self.user,
        )

        with self.assertRaisesMessage(ValidationError, "Bitte dokumentiere kurz"):
            issue.full_clean()

    def test_admin_records_the_time_and_user_on_resolution(self):
        request = RequestFactory().post("/")
        request.user = self.user
        issue = Issue(
            title="Gelöstes Issue",
            status=Issue.Status.CLOSED,
            assigned_to=self.user,
            resolution_note="Die fehlerhafte Zuordnung wurde korrigiert, damit neue Vorgänge wieder richtig landen.",
        )

        IssueAdmin(Issue, AdminSite()).save_model(request, issue, form=None, change=False)

        self.assertIsNotNone(issue.resolved_at)
        self.assertEqual(issue.resolved_by, self.user)
