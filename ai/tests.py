from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from ai.admin import AIRewriteJobAdmin
from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.services import AIRewriteService
from ai.services.provider import AIProviderService
from products.models import Product


class AIProviderServiceTest(SimpleTestCase):
    def test_extract_message_content_supports_string_content(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": " Hallo Welt ",
                    }
                }
            ]
        }

        result = AIProviderService._extract_message_content(payload)

        self.assertEqual(result, "Hallo Welt")

    def test_extract_message_content_supports_content_parts(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Teil 1 "},
                            {"type": "text", "text": "Teil 2"},
                        ]
                    }
                }
            ]
        }

        result = AIProviderService._extract_message_content(payload)

        self.assertEqual(result, "Teil 1 Teil 2")


class AIModelShapeTest(TestCase):
    def test_prompt_has_only_slim_fields(self):
        prompt = AIRewritePrompt.objects.create(
            name="SEO", system_prompt="Schreibe verkaufsstark um."
        )
        self.assertTrue(prompt.slug)
        self.assertTrue(prompt.is_active)
        field_names = {f.name for f in AIRewritePrompt._meta.get_fields()}
        for removed in ("provider", "content_type", "source_field", "target_field",
                        "output_format", "user_prompt_template", "temperature_override"):
            self.assertNotIn(removed, field_names)

    def test_job_uses_product_fk_and_single_field(self):
        provider = AIProviderConfig.objects.create(name="P", model_name="gpt-5-mini")
        prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        product = Product.objects.create(erp_nr="T-1", name="Test")
        job = AIRewriteJob.objects.create(
            product=product, field="description_de", prompt=prompt,
            provider=provider, source_snapshot="<p>alt</p>",
        )
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        field_names = {f.name for f in AIRewriteJob._meta.get_fields()}
        for removed in ("content_type", "object_id", "object_repr", "approved_by",
                        "approved_at", "is_archived", "source_field", "target_field"):
            self.assertNotIn(removed, field_names)


class AIRewriteServiceTest(TestCase):
    def setUp(self):
        self.provider = AIProviderConfig.objects.create(name="P", model_name="gpt-5-mini", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="Schreibe um.")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")

    def test_create_job_is_queued_with_snapshot(self):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        self.assertEqual(job.source_snapshot, "<p>alt</p>")
        self.assertEqual(job.result_text, "")

    @patch("ai.services.rewrite.AIProviderService.rewrite_text", return_value="<p>neu</p>")
    def test_execute_sets_ready(self, _mock):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        AIRewriteService().execute(job)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.READY)
        self.assertEqual(job.result_text, "<p>neu</p>")

    @patch("ai.services.rewrite.AIProviderService.rewrite_text", side_effect=RuntimeError("boom"))
    def test_execute_failure_sets_failed(self, _mock):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        AIRewriteService().execute(job)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.FAILED)
        self.assertIn("boom", job.error_message)

    def test_apply_writes_edited_text_to_field(self):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        job.result_text = "<p>final</p>"
        job.status = AIRewriteJob.Status.READY
        job.save(update_fields=["result_text", "status"])
        AIRewriteService().apply(job=job)
        job.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.product.description_de, "<p>final</p>")
        self.assertEqual(job.status, AIRewriteJob.Status.APPLIED)
        self.assertIsNotNone(job.applied_at)


class AIRewriteTaskTest(TestCase):
    @patch("ai.services.rewrite.AIProviderService.rewrite_text", return_value="<p>neu</p>")
    def test_task_executes_job(self, _mock):
        provider = AIProviderConfig.objects.create(name="P", model_name="m", api_key="k")
        prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")
        job = AIRewriteService().create_job(
            product=product, field="description_de", prompt=prompt, provider=provider,
        )
        from ai.tasks import run_ai_rewrite_job
        run_ai_rewrite_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.READY)


class AIRewriteCreateViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", "a@b.de", "pw")
        self.client.force_login(self.user)
        self.provider = AIProviderConfig.objects.create(name="P", model_name="m", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")

    def test_get_renders_with_product_and_field(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.get(url, {"product": self.product.pk, "field": "description_de"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "description_de")

    @patch("ai.admin.run_ai_rewrite_job.delay")
    def test_post_creates_job_and_redirects(self, mock_delay):
        mock_delay.return_value.id = "task-123"
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.post(url, {
            "product": self.product.pk, "field": "description_de",
            "prompt": self.prompt.pk, "provider": self.provider.pk,
        })
        job = AIRewriteJob.objects.get()
        self.assertEqual(job.field, "description_de")
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        self.assertEqual(job.celery_task_id, "task-123")
        mock_delay.assert_called_once_with(job.pk)
        self.assertRedirects(resp, reverse("admin:ai_airewritejob_change", args=(job.pk,)))

    def test_post_rejects_field_outside_whitelist(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.post(url, {
            "product": self.product.pk, "field": "sku",
            "prompt": self.prompt.pk, "provider": self.provider.pk,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AIRewriteJob.objects.count(), 0)


class AIRewriteJobWorkspaceTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin2", "a2@b.de", "pw")
        self.client.force_login(self.user)
        self.provider = AIProviderConfig.objects.create(name="P", model_name="m", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")

    def _job(self, **overrides):
        data = dict(product=self.product, field="description_de", prompt=self.prompt,
                    provider=self.provider, source_snapshot="<p>alt</p>")
        data.update(overrides)
        return AIRewriteJob.objects.create(**data)

    def _request(self):
        request = RequestFactory().post("/")
        request.user = self.user
        setattr(request, "session", self.client.session)
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def test_change_page_renders_for_ready_job(self):
        job = self._job(status=AIRewriteJob.Status.READY, result_text="<p>neu</p>")
        resp = self.client.get(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
        self.assertEqual(resp.status_code, 200)

    def test_change_page_shows_processing_hint_for_queued_job(self):
        job = self._job(status=AIRewriteJob.Status.QUEUED)
        resp = self.client.get(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "verarbeitet")

    def test_apply_detail_writes_field(self):
        job = self._job(status=AIRewriteJob.Status.READY, result_text="<p>neu</p>")
        admin_obj = AIRewriteJobAdmin(AIRewriteJob, AdminSite())
        admin_obj.apply_rewrite_detail(self._request(), str(job.pk))
        job.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.product.description_de, "<p>neu</p>")
        self.assertEqual(job.status, AIRewriteJob.Status.APPLIED)
