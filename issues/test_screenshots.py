from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from issues.admin import IssueAdmin, IssueReplyForm
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from issues.models import Issue, IssueAttachment, IssueMessage


def screenshot(name="screen.png"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class IssueReplyFormImageTest(SimpleTestCase):
    def test_image_without_text_is_valid(self):
        form = IssueReplyForm({"text": "", "quote": ""}, uploads=[screenshot()])
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_image_is_rejected(self):
        fake = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        form = IssueReplyForm({"text": "Test"}, uploads=[fake])
        self.assertFalse(form.is_valid())
        self.assertIn("gültiges Bild", str(form.errors))

    def test_more_than_five_images_are_rejected(self):
        form = IssueReplyForm({"text": "Test"}, uploads=[screenshot(f"{n}.png") for n in range(6)])
        self.assertFalse(form.is_valid())
        self.assertIn("höchstens 5", str(form.errors))


class IssueScreenshotReplyTest(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.reporter = get_user_model().objects.create_user(
            username="screenshot-reporter", password="test", is_staff=True
        )
        self.assignee = get_user_model().objects.create_user(
            username="screenshot-assignee", password="test", is_staff=True
        )
        self.issue = Issue.objects.create(
            title="Screenshot-Test", reported_by=self.reporter, assigned_to=self.assignee
        )
        self.reply_url = reverse("admin:issues_issue_reply", args=[self.issue.pk])
        self.client.force_login(self.assignee)

    def test_screenshot_and_text_share_one_message_and_keep_quote(self):
        original = IssueMessage.objects.create(
            issue=self.issue, author=self.reporter, text="Original"
        )
        response = self.client.post(
            self.reply_url,
            {"text": "Hier tritt der Fehler auf", "quote": str(original.pk),
             "images": [screenshot("one.png"), screenshot("two.png")]},
        )
        self.assertEqual(response.status_code, 302)
        message = IssueMessage.objects.get(issue=self.issue, text="Hier tritt der Fehler auf")
        self.assertEqual(message.quoted_message, original)
        self.assertEqual(message.attachments.count(), 2)
        self.assertFalse(IssueAttachment.objects.filter(message=message).exclude(issue=self.issue).exists())
        page = self.client.get(reverse("admin:issues_issue_change", args=[self.issue.pk]))
        self.assertContains(page, "Screenshot zur Nachricht")
        self.assertContains(page, "Hier tritt der Fehler auf")

    def test_image_only_message_is_saved(self):
        response = self.client.post(self.reply_url, {"text": "", "images": [screenshot()]})
        self.assertEqual(response.status_code, 302)
        message = IssueMessage.objects.get(issue=self.issue)
        self.assertEqual(message.text, "")
        self.assertEqual(message.attachments.count(), 1)
        request = RequestFactory().get("/admin/issues/issue/")
        request.user = self.reporter
        model_admin = IssueAdmin(Issue, AdminSite())
        listed_issue = model_admin.get_queryset(request).get(pk=self.issue.pk)
        self.assertIn("Screenshot", str(model_admin.last_reply_preview(listed_issue)))

    def test_invalid_image_does_not_create_a_message(self):
        fake = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        response = self.client.post(self.reply_url, {"text": "Test", "images": [fake]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(IssueMessage.objects.filter(issue=self.issue).exists())
        self.assertFalse(IssueAttachment.objects.filter(issue=self.issue).exists())

    def test_nonparticipant_cannot_upload(self):
        outsider = get_user_model().objects.create_user(
            username="screenshot-outsider", password="test", is_staff=True
        )
        self.client.force_login(outsider)
        response = self.client.post(self.reply_url, {"images": [screenshot()]})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(IssueMessage.objects.filter(issue=self.issue).exists())
