from django.apps import apps
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from issues.admin import IssueAdmin
from issues.models import Issue, IssueMessage
from issues.services import create_task_issue
from issues.signals import backfill_initial_messages


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
        initial = IssueMessage.objects.get(issue=self.issue, is_initial=True)
        self.assertEqual(initial.author, self.reporter)
        self.assertEqual(initial.text, self.issue.error_text)
        self.assertEqual(initial.created_at, self.issue.created_at)

        self.client.force_login(self.reporter)
        response = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Erster Fehler &lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertEqual(
            response.content.decode().count("Erster Fehler &lt;script&gt;alert(1)&lt;/script&gt;"),
            1,
        )
        self.assertNotContains(response, "Erster Fehler <script>alert(1)</script>", html=False)
        self.assertNotIn("error_text", response.context["adminform"].form.fields)
        self.assertContains(response, "reporter")

    def test_participants_reply_and_quote_both_initial_and_later_messages(self):
        initial = IssueMessage.objects.get(issue=self.issue, is_initial=True)
        self.client.force_login(self.assignee)
        response = self.client.post(
            self.reply_url(), {"text": "Ich prüfe das.", "quote": str(initial.pk)}
        )
        self.assertEqual(response.status_code, 302)
        first = IssueMessage.objects.get(issue=self.issue, is_initial=False)
        self.assertEqual(first.author, self.assignee)
        self.assertEqual(first.quoted_message, initial)

        self.client.force_login(self.reporter)
        self.client.post(
            self.reply_url(), {"text": "Danke, hier ist ein Beispiel.", "quote": str(first.pk)}
        )
        second = IssueMessage.objects.get(issue=self.issue, author=self.reporter, is_initial=False)
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
        self.assertEqual(IssueMessage.objects.filter(issue=self.issue).count(), 1)

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

    def test_admin_creation_assigns_initial_message_to_logged_in_user(self):
        request = RequestFactory().post("/admin/issues/issue/add/")
        request.user = self.reporter
        issue = Issue(title="Neue Meldung", assigned_to=self.assignee, error_text="Mein Fehlertext")

        IssueAdmin(Issue, AdminSite()).save_model(request, issue, form=None, change=False)

        initial = IssueMessage.objects.get(issue=issue, is_initial=True)
        self.assertEqual(initial.author, self.reporter)
        self.assertEqual(initial.text, "Mein Fehlertext")

    def test_existing_error_text_is_backfilled_once_with_original_author_and_time(self):
        issue = Issue.objects.create(
            title="Altes Issue", reported_by=self.reporter, assigned_to=self.assignee
        )
        Issue.objects.filter(pk=issue.pk).update(error_text="Alter Fehlertext")

        for _ in range(2):
            backfill_initial_messages(
                sender=apps.get_app_config("issues"), apps=apps, using="default"
            )

        initial = IssueMessage.objects.get(issue=issue, is_initial=True)
        self.assertEqual(initial.author, self.reporter)
        self.assertEqual(initial.text, "Alter Fehlertext")
        self.assertEqual(initial.created_at, issue.created_at)
        self.assertEqual(IssueMessage.objects.filter(issue=issue, is_initial=True).count(), 1)

    def test_old_quotes_of_the_initial_text_still_display_the_author(self):
        IssueMessage.objects.create(
            issue=self.issue,
            author=self.assignee,
            text="Alte Antwort",
            quotes_initial=True,
        )
        self.client.force_login(self.reporter)

        response = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))

        self.assertContains(response, "Alte Antwort")
        self.assertContains(response, "reporter")
        self.assertContains(response, "Erster Fehler &lt;script&gt;alert(1)&lt;/script&gt;")

    def test_existing_error_text_is_first_even_without_a_backfilled_message(self):
        issue = Issue.objects.create(
            title="Noch nicht übernommenes Issue",
            reported_by=self.reporter,
            assigned_to=self.assignee,
        )
        Issue.objects.filter(pk=issue.pk).update(error_text="Vorhandener Fehlertext")
        self.client.force_login(self.reporter)

        response = self.client.get(reverse("admin:issues_issue_change", args=[issue.pk]))

        self.assertContains(response, "Vorhandener Fehlertext")
        self.assertEqual(response.context["chat_entries"][0]["author"], "reporter")
        self.assertEqual(response.context["chat_entries"][0]["quote_key"], "initial")

        self.client.post(self.reply_url(issue), {"text": "Antwort", "quote": "initial"})
        self.assertTrue(
            IssueMessage.objects.filter(issue=issue, text="Antwort", quotes_initial=True).exists()
        )
