from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ai.admin import AIRewriteJobAdmin, AIRewriteJobRequestForm
from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.management.commands.import_legacy_ai_rewrites import Command as ImportLegacyAIRewritesCommand
from ai.services import AIRewriteApplyService
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


class ImportLegacyAIRewritesCommandTest(SimpleTestCase):
    def test_map_field_name_maps_legacy_description_fields(self):
        command = ImportLegacyAIRewritesCommand()

        self.assertEqual(command._map_field_name("description"), "description_de")
        self.assertEqual(command._map_field_name("description_short"), "description_short_de")

    def test_normalize_result_text_unwraps_json_string(self):
        result = ImportLegacyAIRewritesCommand._normalize_result_text('"Hallo"')

        self.assertEqual(result, "Hallo")

    def test_map_status_marks_matching_legacy_value_as_applied(self):
        command = ImportLegacyAIRewritesCommand()

        status = command._map_status(
            legacy_status="FOR_APPROVAL",
            legacy_target_value="<p>Text</p>",
            result_text="<p>Text</p>",
        )

        self.assertEqual(status, "applied")

    def test_resolve_sqlite_path_builds_from_dump_when_missing(self):
        command = ImportLegacyAIRewritesCommand()

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dump_path = temp_path / "database.sql"
            sqlite_path = temp_path / "legacy.sqlite3"
            dump_path.write_text("-- dump", encoding="utf-8")

            with patch("ai.management.commands.import_legacy_ai_rewrites.call_command") as mocked_call_command:
                def _create_sqlite(*args, **kwargs):
                    sqlite_path.write_text("", encoding="utf-8")

                mocked_call_command.side_effect = _create_sqlite

                resolved_path = command._resolve_sqlite_path(
                    sqlite_path_value=str(sqlite_path),
                    dump_path_value=str(dump_path),
                    rebuild_sqlite=False,
                )

            self.assertEqual(resolved_path, sqlite_path.resolve())
            mocked_call_command.assert_called_once_with(
                "legacy_dump_to_sqlite",
                str(dump_path.resolve()),
                str(sqlite_path.resolve()),
                overwrite=True,
            )

    def test_resolve_sqlite_path_raises_when_neither_dump_nor_sqlite_exists(self):
        command = ImportLegacyAIRewritesCommand()

        with TemporaryDirectory() as temp_dir:
            missing_sqlite = Path(temp_dir) / "missing.sqlite3"

            with self.assertRaises(CommandError):
                command._resolve_sqlite_path(
                    sqlite_path_value=str(missing_sqlite),
                    dump_path_value="",
                    rebuild_sqlite=False,
                )


class AIRewriteJobAdminTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="ai-admin",
            email="ai-admin@example.com",
            password="pass",
        )
        self.product = Product.objects.create(
            erp_nr="581001",
            name="Rewrite Produkt",
            description_de="<p>Aktueller Inhalt</p>",
            description_short_de="<p>Kurz aktuell</p>",
        )
        self.provider = AIProviderConfig.objects.create(
            name="Test Provider",
            model_name="gpt-5-mini",
        )
        self.prompt = AIRewritePrompt.objects.create(
            name="Beschreibung SEO",
            provider=self.provider,
            content_type=ContentType.objects.get_for_model(Product),
            source_field="description_de",
            target_field="description_de",
            system_prompt="Bitte umschreiben",
        )
        self.short_prompt = AIRewritePrompt.objects.create(
            name="Kurzbeschreibung",
            provider=self.provider,
            content_type=ContentType.objects.get_for_model(Product),
            source_field="description_short_de",
            target_field="description_short_de",
            system_prompt="Bitte kurz umschreiben",
        )
        self.job = AIRewriteJob.objects.create(
            content_type=ContentType.objects.get_for_model(Product),
            object_id=self.product.pk,
            object_repr=str(self.product),
            prompt=self.prompt,
            provider=self.provider,
            source_field="description_de",
            target_field="description_de",
            source_snapshot="<p>Alter Inhalt</p>",
            result_text="<p>Neuer Inhalt</p>",
            requested_by=self.user,
            status=AIRewriteJob.Status.PENDING_REVIEW,
        )
        self.admin_instance = AIRewriteJobAdmin(AIRewriteJob, AdminSite())
        self.client.force_login(self.user)

    def test_request_form_filters_prompts_by_target_field(self):
        form = AIRewriteJobRequestForm(initial={"target_field": "description_de"})

        self.assertEqual(list(form.fields["prompt"].queryset), [self.prompt])

    def test_request_form_lists_rewriteable_product_fields_even_without_prompts(self):
        AIRewritePrompt.objects.all().delete()

        form = AIRewriteJobRequestForm(initial={"target_field": "description_de"})

        target_field_names = [field_name for field_name, _label in form.fields["target_field"].choices]
        self.assertIn("description_de", target_field_names)
        self.assertIn("name_de", target_field_names)
        self.assertEqual(list(form.fields["prompt"].queryset), [])

    def test_request_form_uses_unfold_autocomplete_widgets(self):
        form = AIRewriteJobRequestForm(
            initial={
                "product": self.product.pk,
                "target_field": "description_de",
            }
        )

        self.assertEqual(form.fields["product"].widget.attrs["data-theme"], "admin-autocomplete")
        self.assertEqual(form.fields["target_field"].widget.attrs["data-theme"], "admin-autocomplete")
        self.assertEqual(form.fields["prompt"].widget.attrs["data-theme"], "admin-autocomplete")

    def test_job_list_links_point_to_job_change_view(self):
        self.assertEqual(self.admin_instance.list_display_links, ("job_label",))
        self.assertIn("#", self.admin_instance.job_label(self.job))

    def test_product_link_points_to_product_change_view(self):
        html = self.admin_instance.product_link(self.job)

        self.assertIn(reverse("admin:products_product_change", args=(self.product.pk,)), html)
        self.assertIn(self.product.erp_nr, html)

    def test_current_target_preview_uses_wysiwyg_style_and_live_product_field_value(self):
        html = self.admin_instance.current_target_preview(self.job)

        self.assertIn("trix-content", html)
        self.assertIn("<p>Aktueller Inhalt</p>", html)

    def test_target_reference_combines_object_and_object_id(self):
        html = self.admin_instance.target_reference(self.job)

        self.assertIn("Objekt-ID", html)
        self.assertIn(str(self.product.pk), html)
        self.assertIn(self.product.erp_nr, html)

    def test_product_inline_preview_shows_product_information(self):
        html = self.admin_instance.product_inline_preview(self.job)

        self.assertIn("ERP-Nr.", html)
        self.assertIn(self.product.erp_nr, html)
        self.assertIn("Rewrite Produkt", html)

    def test_fieldsets_are_grouped_as_tabs_with_metadata_last(self):
        fieldset_titles = [fieldset[0] for fieldset in self.admin_instance.fieldsets]
        fieldset_classes = [fieldset[1].get("classes", ()) for fieldset in self.admin_instance.fieldsets]

        self.assertEqual(fieldset_titles, ["Freigabe", "Produkt", "Prompt", "Metadaten"])
        self.assertTrue(all("tab" in classes for classes in fieldset_classes))

    def test_apply_service_marks_job_as_archived(self):
        AIRewriteApplyService().apply(job=self.job, approved_by=self.user)

        self.job.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.job.status, AIRewriteJob.Status.APPLIED)
        self.assertTrue(self.job.is_archived)
        self.assertEqual(self.product.description_de, "<p>Neuer Inhalt</p>")

    def test_request_view_renders_unfold_widgets(self):
        response = self.client.get(
            reverse("admin:ai_airewritejob_request"),
            {
                "product": self.product.pk,
                "target_field": "description_de",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unfold-admin-autocomplete")
        self.assertContains(response, "Rewrite erzeugen")

    def test_product_change_view_exposes_ai_field_button_config(self):
        response = self.client.get(reverse("admin:products_product_change", args=(self.product.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "product-ai-rewrite-fields")
        self.assertContains(response, "description_de")
        self.assertContains(response, "description_short_de")
        self.assertContains(response, reverse("admin:products_product_request_ai_rewrite", args=(self.product.pk,)))

    @patch("products.admin.AIRewriteService.request_rewrite")
    def test_product_field_action_creates_job_when_single_prompt(self, mocked_request_rewrite):
        mocked_request_rewrite.return_value = self.job

        response = self.client.post(
            reverse("admin:products_product_request_ai_rewrite", args=(self.product.pk,)),
            {"target_field": "description_de"},
        )

        self.assertRedirects(response, reverse("admin:ai_airewritejob_change", args=(self.job.pk,)))
        mocked_request_rewrite.assert_called_once_with(
            content_object=self.product,
            prompt=self.prompt,
            requested_by=self.user,
        )

    def test_product_field_action_redirects_to_request_page_when_multiple_prompts_exist(self):
        AIRewritePrompt.objects.create(
            name="Beschreibung Marktplatz",
            provider=self.provider,
            content_type=ContentType.objects.get_for_model(Product),
            source_field="description_de",
            target_field="description_de",
            system_prompt="Alternative Variante",
        )

        response = self.client.post(
            reverse("admin:products_product_request_ai_rewrite", args=(self.product.pk,)),
            {"target_field": "description_de"},
        )

        self.assertRedirects(
            response,
            f"{reverse('admin:ai_airewritejob_request')}?product={self.product.pk}&target_field=description_de",
            fetch_redirect_response=False,
        )

    def test_product_field_action_redirects_to_request_page_when_no_prompt_exists(self):
        response = self.client.post(
            reverse("admin:products_product_request_ai_rewrite", args=(self.product.pk,)),
            {"target_field": "name_de"},
        )

        self.assertRedirects(
            response,
            f"{reverse('admin:ai_airewritejob_request')}?product={self.product.pk}&target_field=name_de",
            fetch_redirect_response=False,
        )
