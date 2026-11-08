from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from issues.models import Issue, IssueMessage, IssueNotification


class IssueNotificationTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.reporter = user_model.objects.create_user(id=1, username="reporter", password="test", is_staff=True)
        self.assignee = user_model.objects.create_user(username="assignee", password="test", is_staff=True)
        self.contributor = user_model.objects.create_user(username="contributor", password="test", is_staff=True)
        self.outsider = user_model.objects.create_user(username="outsider", password="test", is_staff=True)
        self.issue = Issue.objects.create(title="Benachrichtigungstest", reported_by=self.reporter, assigned_to=self.assignee)

    def test_status_change_notifies_reporter_assignee_and_chat_contributor(self):
        IssueMessage.objects.create(issue=self.issue, author=self.contributor, body="Ich prüfe das.")
        IssueNotification.objects.all().delete()

        self.issue._issue_notification_actor = self.assignee
        self.issue.status = Issue.Status.IN_PROGRESS
        self.issue.save(update_fields=("status", "updated_at"))

        notifications = IssueNotification.objects.filter(kind=IssueNotification.Kind.STATUS)
        self.assertEqual(set(notifications.values_list("user_id", flat=True)), {self.reporter.pk, self.contributor.pk})
        self.assertTrue(all(item.detail == "In Bearbeitung" for item in notifications))
        self.assertFalse(notifications.filter(user=self.outsider).exists())

    def test_message_post_creates_unread_notifications_and_chat_entry(self):
        self.client.force_login(self.contributor)
        response = self.client.post(
            reverse("admin:issues_issue_message", args=(self.issue.pk,)),
            {"body": "Neue Rückfrage"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(IssueMessage.objects.get(issue=self.issue).body, "Neue Rückfrage")
        self.assertEqual(
            set(IssueNotification.objects.values_list("user_id", flat=True)),
            {self.reporter.pk, self.assignee.pk},
        )
        self.assertFalse(IssueNotification.objects.filter(user=self.contributor).exists())

    def test_notification_api_only_exposes_and_marks_own_items(self):
        IssueMessage.objects.create(issue=self.issue, author=self.assignee, body="Antwort")
        self.client.force_login(self.reporter)
        url = reverse("admin:issues_issue_notifications")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["notifications"][0]["kind"], "message")

        notification = IssueNotification.objects.get(user=self.reporter)
        foreign = IssueNotification.objects.create(
            issue=self.issue,
            user=self.outsider,
            kind=IssueNotification.Kind.MESSAGE,
        )
        self.client.post(url, {"id": foreign.pk})
        foreign.refresh_from_db()
        self.assertIsNone(foreign.read_at)
        self.client.post(url, {"id": notification.pk})
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)
        self.assertEqual(self.client.get(url).json()["count"], 0)

    def test_opening_issue_marks_its_notifications_read(self):
        IssueMessage.objects.create(issue=self.issue, author=self.assignee, body="Antwort")
        self.client.force_login(self.reporter)
        response = self.client.get(reverse("admin:issues_issue_change", args=(self.issue.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chatverlauf")
        self.assertContains(response, "Antwort")
        self.assertContains(response, 'id="issue-notifications"')
        self.assertFalse(IssueNotification.objects.filter(user=self.reporter, read_at__isnull=True).exists())
