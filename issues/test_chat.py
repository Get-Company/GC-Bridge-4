from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from issues.models import Issue, IssueAttachment, IssueMessage


def screenshot(name="screen.png"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class IssueChatTest(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = get_user_model().objects.create_user(
            id=1, username="chat-user", password="test-password", is_staff=True
        )
        self.issue = Issue.objects.create(title="Screenshot-Test", assigned_to=self.user)
        self.url = reverse("admin:issues_issue_message", args=[self.issue.pk])
        self.client.force_login(self.user)

    def test_image_and_text_are_saved_on_same_message_and_issue(self):
        response = self.client.post(
            self.url,
            {"body": "Hier tritt der Fehler auf", "images": [screenshot()]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        message = IssueMessage.objects.get()
        attachment = IssueAttachment.objects.get()
        self.assertEqual(message.issue, self.issue)
        self.assertEqual(message.author, self.user)
        self.assertEqual(message.body, "Hier tritt der Fehler auf")
        self.assertEqual(attachment.issue, self.issue)
        self.assertEqual(attachment.message, message)
        self.assertIn("Screenshot zur Nachricht", response.json()["html"])

    def test_image_without_text_is_allowed(self):
        response = self.client.post(self.url, {"body": "", "images": [screenshot()]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IssueMessage.objects.get().body, "")

    def test_multiple_images_belong_to_one_message(self):
        response = self.client.post(
            self.url, {"body": "Zwei Ansichten", "images": [screenshot("one.png"), screenshot("two.png")]}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IssueMessage.objects.count(), 1)
        self.assertEqual(IssueMessage.objects.get().attachments.count(), 2)

    def test_invalid_image_rejected_without_message(self):
        fake = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        response = self.client.post(
            self.url, {"body": "Test", "images": [fake]}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(IssueMessage.objects.exists())
        self.assertFalse(IssueAttachment.objects.exists())

    def test_empty_post_rejected(self):
        response = self.client.post(self.url, {"body": "  "}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(IssueMessage.objects.exists())

    def test_non_staff_cannot_post(self):
        outsider = get_user_model().objects.create_user(username="outsider", password="test-password")
        self.client.force_login(outsider)
        response = self.client.post(self.url, {"body": "Unbefugt"})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(IssueMessage.objects.exists())

    def test_message_is_visible_on_issue_change_page(self):
        IssueMessage.objects.create(issue=self.issue, author=self.user, body="Vorhandene Nachricht")
        response = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vorhandene Nachricht")
        self.assertContains(response, "issue-chat-images")

    def test_archived_issue_can_keep_chatting(self):
        self.issue.status = Issue.Status.CLOSED
        self.issue.resolution_note = "Fehler behoben"
        self.issue.save()
        url = reverse("admin:issues_issue_message", args=[self.issue.pk])
        response = self.client.post(url, {"body": "Nachtrag im Archiv"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IssueMessage.objects.get().body, "Nachtrag im Archiv")
