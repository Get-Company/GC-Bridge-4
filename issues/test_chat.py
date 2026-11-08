from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from issues.models import Issue, IssueMessage
from issues.services import create_task_issue


class IssueChatTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.reporter = user_model.objects.create_user(
            username="reporter", password="test", is_staff=True
        )
        cls.assignee = user_model.objects.create_user(
            username="assignee", password="test", is_staff=True
        )
        cls.outsider = user_model.objects.create_user(
            username="outsider", password="test", is_staff=True
        )
        cls.issue = Issue.objects.create(
            title="Fehler im Ablauf",
            reported_by=cls.reporter,
            assigned_to=cls.assignee,
            error_text="Erster Fehler <script>alert(1)</script>",
        )
        cls.other_issue = Issue.objects.create(
            title="Anderer Fehler", reported_by=cls.reporter, assigned_to=cls.assignee
        )

    def reply_url(self, issue=None, archived=False):
        name = "admin:issues_archivedissue_reply" if archived else "admin:issues_issue_reply"
        return reverse(name, args=[(issue or self.issue).pk])

    def test_initial_message_is_shown_safely_and_is_no_longer_editable(self):
        self.client.force_login(self.reporter)
        response = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Erster Fehler &lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "Erster Fehler <script>alert(1)</script>", html=False)
        self.assertNotIn("error_text", response.context["adminform"].form.fields)
        self.assertContains(response, "reporter")

    def test_participants_reply_and_quote_both_initial_and_later_messages(self):
        self.client.force_login(self.assignee)
        response = self.client.post(
            self.reply_url(), {"text": "Ich prüfe das.", "quote": "initial"}
        )
        self.assertEqual(response.status_code, 302)
        first = IssueMessage.objects.get(issue=self.issue)
        self.assertEqual(first.author, self.assignee)
        self.assertTrue(first.quotes_initial)

        self.client.force_login(self.reporter)
        self.client.post(
            self.reply_url(), {"text": "Danke, hier ist ein Beispiel.", "quote": str(first.pk)}
        )
        second = IssueMessage.objects.get(issue=self.issue, author=self.reporter)
        self.assertEqual(second.quoted_message, first)
        response = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))
        self.assertContains(response, "Ich prüfe das.")
        self.assertContains(response, "Danke, hier ist ein Beispiel.")

    def test_only_participants_can_post_and_quotes_stay_within_the_issue(self):
        other_message = IssueMessage.objects.create(
            issue=self.other_issue, author=self.reporter, text="Anderes Issue"
        )
        self.client.force_login(self.outsider)
        response = self.client.post(self.reply_url(), {"text": "Unbefugte Antwort"})
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.assignee)
        response = self.client.post(
            self.reply_url(), {"text": "Falsches Zitat", "quote": str(other_message.pk)}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(IssueMessage.objects.filter(issue=self.issue).exists())

    def test_archive_uses_the_same_conversation(self):
        self.issue.status = Issue.Status.RESOLVED
        self.issue.resolution_note = "Fehler behoben."
        self.issue.save()
        self.client.force_login(self.assignee)

        response = self.client.post(self.reply_url(archived=True), {"text": "Abschluss bestätigt"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(IssueMessage.objects.filter(issue=self.issue, text="Abschluss bestätigt").exists())
        response = self.client.get(
            reverse("admin:issues_archivedissue_change", args=[self.issue.pk])
        )
        self.assertContains(response, "Abschluss bestätigt")

    def test_later_automatic_errors_are_separate_system_messages(self):
        original = self.issue.error_text
        result = create_task_issue(title=self.issue.title, error_text="Neuer Task-Fehler")

        self.assertEqual(result, self.issue)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.error_text, original)
        self.assertTrue(
            IssueMessage.objects.filter(
                issue=self.issue, author__isnull=True, text="Neuer Task-Fehler"
            ).exists()
        )
