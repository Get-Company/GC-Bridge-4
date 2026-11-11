from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from issues.admin import IssueAdmin
from issues.models import Issue, IssueMessage, IssueReadState


class IssueListUnreadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.reporter = user_model.objects.create_user(
            username="reporter", password="test", is_staff=True
        )
        cls.assignee = user_model.objects.create_user(
            username="assignee", password="test", is_staff=True
        )
        cls.issue = Issue.objects.create(
            title="Frage zur Rechnung",
            description="Bestehende Fehlerbeschreibung",
            reported_by=cls.reporter,
            assigned_to=cls.assignee,
        )

    def list_issue_for(self, user):
        request = RequestFactory().get("/admin/issues/issue/")
        request.user = user
        admin = IssueAdmin(Issue, AdminSite())
        issue = admin.get_queryset(request).get(pk=self.issue.pk)
        return admin, issue

    def test_foreign_reply_is_bold_until_opened_and_preview_is_one_line(self):
        admin, issue = self.list_issue_for(self.reporter)
        self.assertFalse(admin._has_unread_reply(issue))
        self.assertEqual(admin.last_reply_preview(issue), "–")

        reply = IssueMessage.objects.create(
            issue=self.issue,
            author=self.assignee,
            text="Ich prüfe\n  die Nummer <heute>.",
        )
        admin, issue = self.list_issue_for(self.reporter)
        self.assertTrue(admin._has_unread_reply(issue))
        self.assertIn("<strong", admin.issue_title(issue))
        self.assertIn(">mail</span>", admin.issue_title(issue))
        preview = str(admin.last_reply_preview(issue))
        self.assertIn("Ich prüfe die Nummer &lt;heute&gt;.", preview)
        self.assertNotIn("\n", preview)

        self.client.force_login(self.reporter)
        response = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            IssueReadState.objects.get(issue=self.issue, user=self.reporter).last_seen_message_id,
            reply.pk,
        )
        admin, issue = self.list_issue_for(self.reporter)
        self.assertFalse(admin._has_unread_reply(issue))
        self.assertNotIn("<strong", str(admin.issue_title(issue)))
        self.assertIn(">drafts</span>", admin.issue_title(issue))

        IssueMessage.objects.create(issue=self.issue, author=self.reporter, text="Danke.")
        admin, issue = self.list_issue_for(self.reporter)
        self.assertFalse(admin._has_unread_reply(issue))
        self.assertIn("Danke.", str(admin.last_reply_preview(issue)))

        admin, issue = self.list_issue_for(self.assignee)
        self.assertTrue(admin._has_unread_reply(issue))

    def test_initial_message_does_not_mark_issue_unread(self):
        IssueMessage.objects.create(
            issue=self.issue,
            author=self.reporter,
            text="Technischer Fehlertext",
            is_initial=True,
        )
        admin, issue = self.list_issue_for(self.assignee)
        self.assertFalse(admin._has_unread_reply(issue))
        self.assertEqual(admin.last_reply_preview(issue), "–")
