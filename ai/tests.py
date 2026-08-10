import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from ai.admin import AIRewriteJobAdmin
from ai.models import (
    AIProviderConfig,
    AIRewriteJob,
    AIRewritePrompt,
    AITranslationConfig,
    AITranslationGlossaryEntry,
    AITranslationState,
)
from ai.services import AIRewriteService, AITranslationService
from ai.services.provider import AIProviderService
from products.models import (
    Category,
    Product,
    ProductProperty,
    ProductSyncJob,
    ProductVariantFamily,
    PropertyGroup,
    PropertyValue,
)


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

    @patch("ai.services.provider.urllib.request.urlopen")
    def test_local_provider_allows_empty_api_key_and_structured_response(self, mock_urlopen):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read():
                return b'{"choices": [{"message": {"content": "{}"}}]}'

        mock_urlopen.return_value = Response()
        provider = SimpleNamespace(
            name="Ollama im LAN",
            api_key="",
            base_url="http://10.0.0.42:11434/v1",
            model_name="translategemma:12b",
            temperature=0,
            timeout_seconds=60,
        )

        result = AIProviderService().rewrite_text(
            provider=provider,
            system_prompt="System",
            user_prompt="User",
            response_format={"type": "json_object"},
        )

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, "{}")
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(payload["response_format"], {"type": "json_object"})


class AITranslationMarkupTest(SimpleTestCase):
    def test_scan_discovers_all_registered_customer_translation_fields(self):
        registered_fields = {
            model: set(fields)
            for model, fields in AITranslationService._iter_registered_text_models()
        }

        self.assertTrue({"name", "description"} <= registered_fields[ProductVariantFamily])
        self.assertTrue(
            {
                "name",
                "description",
                "description_short",
                "meta_title",
                "meta_description",
                "meta_keywords",
            }
            <= registered_fields[Category]
        )
        self.assertEqual(registered_fields[PropertyGroup], {"name"})
        self.assertEqual(registered_fields[PropertyValue], {"name"})

    def test_empty_default_language_column_falls_back_to_legacy_german_source(self):
        target = SimpleNamespace(name="Bestehender deutscher Name", name_de="")
        state = SimpleNamespace(
            source_field="name",
            configuration=SimpleNamespace(source_language="de"),
        )

        source = AITranslationService()._source_value(target, state)

        self.assertEqual(source, "Bestehender deutscher Name")

    def test_html_markup_and_non_human_content_stay_unchanged(self):
        segmented = AITranslationService.segment_html_text(
            '<p class="lead"> Hallo <a href="/angebot" style="color:red">Welt</a></p><code>SKU-1</code>'
        )

        self.assertEqual(
            [(segment.identifier, segment.source_text) for segment in segmented.segments],
            [("T0001", "Hallo"), ("T0002", "Welt")],
        )
        self.assertEqual(
            segmented.render({"T0001": "Hello", "T0002": "world"}),
            '<p class="lead"> Hello <a href="/angebot" style="color:red">world</a></p><code>SKU-1</code>',
        )

    def test_model_response_requires_the_exact_segment_ids(self):
        segmented = AITranslationService.segment_html_text("Hallo Welt")

        with self.assertRaisesMessage(ValueError, "Segment-IDs"):
            AITranslationService._parse_translation_response(
                response='{"T0002": "Hello world"}',
                expected_segments=segmented.segments,
            )

    def test_human_readable_html_attributes_are_translated_but_technical_ones_are_preserved(self):
        segmented = AITranslationService.segment_html_text(
            '<img alt="Produktbild" src="/media/product.jpg" class="preview" title="Grossansicht">'
        )

        self.assertEqual(
            [(segment.identifier, segment.source_text) for segment in segmented.segments],
            [("T0001", "Produktbild"), ("T0002", "Grossansicht")],
        )
        self.assertEqual(
            segmented.render({"T0001": "Product image", "T0002": "Large view"}),
            '<img alt="Product image" src="/media/product.jpg" class="preview" title="Large view">',
        )

    def test_it_de_has_a_mandatory_german_output_rule(self):
        rule = AITranslationService._mandatory_output_language_rule("it-de")

        self.assertIn("AUSGABESPRACHE: Deutsch", rule)
        self.assertIn("NICHT fuer Italienisch", rule)


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

    def test_job_uses_a_single_product_or_category_target_and_field(self):
        provider = AIProviderConfig.objects.create(name="P", model_name="gpt-5-mini")
        prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        product = Product.objects.create(erp_nr="T-1", name="Test")
        job = AIRewriteJob.objects.create(
            product=product, field="description_de", prompt=prompt,
            provider=provider, source_snapshot="<p>alt</p>",
        )
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        self.assertEqual(job.target, product)
        field_names = {f.name for f in AIRewriteJob._meta.get_fields()}
        self.assertIn("category", field_names)
        for removed in ("content_type", "object_id", "object_repr", "approved_by",
                        "approved_at", "is_archived", "source_field", "target_field"):
            self.assertNotIn(removed, field_names)


class AITranslationServiceTest(TestCase):
    def setUp(self):
        self.provider = AIProviderConfig.objects.create(
            name="TranslateGemma", model_name="translategemma:12b", api_key=""
        )
        self.configuration = AITranslationConfig.objects.create(
            name="Automatische Uebersetzungen",
            provider=self.provider,
            batch_size=100,
        )
        self.product = Product.objects.create(
            erp_nr="TRANS-1",
            name="Tisch",
            name_de="Tisch",
            description_de='<p class="lead">Hallo <strong>Welt</strong></p>',
        )

    def _queue_description_en(self):
        AITranslationService().queue_pending_translations()
        return AITranslationState.objects.get(
            object_id=self.product.pk,
            source_field="description",
            target_language="en",
        )

    @patch(
        "ai.services.translation.AIProviderService.rewrite_text_with_response",
        return_value=(
            '{"T0001": "Hello", "T0002": "world"}',
            '{"choices": [{"message": {"content": "..."}}]}',
        ),
    )
    def test_changed_source_is_translated_and_html_markup_is_preserved(self, mock_rewrite):
        state = self._queue_description_en()

        with patch("products.tasks.process_product_sync_job.delay") as mock_sync_task:
            mock_sync_task.return_value.id = "sync-1"
            with self.captureOnCommitCallbacks(execute=True):
                AITranslationService().translate_state(state_id=state.pk)

        state.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.product.description_en, '<p class="lead">Hello <strong>world</strong></p>')
        self.assertEqual(state.status, AITranslationState.Status.SUCCEEDED)
        self.assertEqual(mock_rewrite.call_args.kwargs["temperature"], 0)
        self.assertEqual(mock_rewrite.call_args.kwargs["response_format"], {"type": "json_object"})
        translation_syncs = ProductSyncJob.objects.filter(trigger="ai_translation")
        self.assertEqual(list(translation_syncs.values_list("target", flat=True)), [ProductSyncJob.Target.SHOPWARE])

    @patch(
        "ai.services.translation.AIProviderService.rewrite_text_with_response",
        return_value=(
            '{"T0001": "Hello", "T0002": "world"}',
            '{"choices": [{"message": {"content": "..."}}]}',
        ),
    )
    def test_unchanged_source_hash_is_not_queued_again(self, mock_rewrite):
        state = self._queue_description_en()
        with patch("products.tasks.process_product_sync_job.delay") as mock_sync_task:
            mock_sync_task.return_value.id = "sync-2"
            with self.captureOnCommitCallbacks(execute=True):
                AITranslationService().translate_state(state_id=state.pk)

        queued_again = AITranslationService().queue_pending_translations()

        self.assertNotIn(state.pk, queued_again)
        mock_rewrite.assert_called_once()

    @patch(
        "ai.services.translation.AIProviderService.rewrite_text_with_response",
        return_value=(
            '{"T0001": "Hello", "T0002": "world"}',
            '{"choices": [{"message": {"content": "..."}}]}',
        ),
    )
    def test_changed_translation_configuration_requeues_unchanged_source(self, _mock_rewrite):
        state = self._queue_description_en()
        with patch("products.tasks.process_product_sync_job.delay") as mock_sync_task:
            mock_sync_task.return_value.id = "sync-config"
            with self.captureOnCommitCallbacks(execute=True):
                AITranslationService().translate_state(state_id=state.pk)

        state.refresh_from_db()
        previous_configuration_hash = state.configuration_hash
        self.configuration.system_prompt = f"{self.configuration.system_prompt}\nNeue verbindliche Regel."
        self.configuration.save(update_fields=("system_prompt", "updated_at"))

        queued_again = AITranslationService().queue_pending_translations()

        state.refresh_from_db()
        self.assertIn(state.pk, queued_again)
        self.assertEqual(state.status, AITranslationState.Status.PENDING)
        self.assertNotEqual(state.configuration_hash, previous_configuration_hash)

    def test_glossary_change_updates_the_translation_configuration_fingerprint(self):
        fingerprint_without_glossary = AITranslationService.configuration_fingerprint(self.configuration)

        AITranslationGlossaryEntry.objects.create(
            configuration=self.configuration,
            source_term="Orga-Mappen",
            target_language="en",
            target_term="Organizational Folders",
        )

        fingerprint_with_glossary = AITranslationService.configuration_fingerprint(self.configuration)

        self.assertNotEqual(fingerprint_with_glossary, fingerprint_without_glossary)

    def test_glossary_matches_exact_and_similar_terms_but_excludes_unrelated_entries(self):
        exact_entry = AITranslationGlossaryEntry.objects.create(
            configuration=self.configuration,
            source_term="Orga-Mappen",
            target_language="en",
            target_term="Organizational Folders",
        )
        similar_entry = AITranslationGlossaryEntry.objects.create(
            configuration=self.configuration,
            source_term="Lagerplatz",
            target_language="en",
            target_term="Storage Location",
        )
        AITranslationGlossaryEntry.objects.create(
            configuration=self.configuration,
            source_term="Kundenmappe",
            target_language="en",
            target_term="Customer Folder",
        )

        segmented = AITranslationService.segment_html_text(
            "Die Orga Mappen liegen beim Lagerplaz."
        )
        entries = AITranslationService()._relevant_glossary_entries(
            configuration=self.configuration,
            target_language="en",
            segments=segmented.segments,
        )

        self.assertEqual(list(entries), [exact_entry, similar_entry])

    @patch(
        "ai.services.translation.AIProviderService.rewrite_text_with_response",
        return_value=(
            '{"T0001": "Organizational Folders"}',
            '{"choices": [{"message": {"content": "..."}}]}',
        ),
    )
    def test_translation_prompt_contains_only_relevant_glossary_entries(self, mock_rewrite):
        state = self._queue_description_en()
        AITranslationGlossaryEntry.objects.create(
            configuration=self.configuration,
            source_term="Orga-Mappen",
            target_language="en",
            target_term="Organizational Folders",
        )
        AITranslationGlossaryEntry.objects.create(
            configuration=self.configuration,
            source_term="Kundenmappe",
            target_language="en",
            target_term="Customer Folder",
        )
        segments = AITranslationService.segment_html_text("Orga-Mappen")

        AITranslationService()._translate_segments(state=state, segments=segments.segments)

        system_prompt = mock_rewrite.call_args.kwargs["system_prompt"]
        self.assertIn("Organizational Folders", system_prompt)
        self.assertNotIn("Customer Folder", system_prompt)

    def test_expired_success_status_is_archived_without_losing_its_hash(self):
        state = self._queue_description_en()
        state.status = AITranslationState.Status.SUCCEEDED
        state.translated_at = timezone.now() - timedelta(days=31)
        state.save(update_fields=("status", "translated_at", "updated_at"))

        archived_count = AITranslationService().archive_expired_states(configuration=self.configuration)
        queued_again = AITranslationService().queue_pending_translations()

        state.refresh_from_db()
        self.assertEqual(archived_count, 1)
        self.assertTrue(state.is_archived)
        self.assertIsNotNone(state.archived_at)
        self.assertNotIn(state.pk, queued_again)

    @patch(
        "ai.services.translation.AIProviderService.rewrite_text_with_response",
        return_value=(
            '{"T0001": "Updated", "T0002": "text"}',
            '{"choices": [{"message": {"content": "..."}}]}',
        ),
    )
    def test_empty_source_clears_existing_target_when_enabled(self, _mock_rewrite):
        state = self._queue_description_en()
        with patch("products.tasks.process_product_sync_job.delay") as mock_sync_task:
            mock_sync_task.return_value.id = "sync-3"
            with self.captureOnCommitCallbacks(execute=True):
                AITranslationService().translate_state(state_id=state.pk)

        self.product.description_de = ""
        self.product.save(update_fields=("description_de", "updated_at"))
        queued_again = AITranslationService().queue_pending_translations()

        self.assertIn(state.pk, queued_again)
        with patch("products.tasks.process_product_sync_job.delay") as mock_sync_task:
            mock_sync_task.return_value.id = "sync-4"
            with self.captureOnCommitCallbacks(execute=True):
                AITranslationService().translate_state(state_id=state.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.description_en, "")

    @patch(
        "ai.services.translation.AIProviderService.rewrite_text_with_response",
        return_value=(
            '{"T0001": "Folders"}',
            '{"choices": [{"message": {"content": "..."}}]}',
        ),
    )
    @patch("products.tasks.sync_category_translations_to_shopware.delay")
    def test_category_translation_schedules_a_shopware_only_translation_sync(self, mock_sync_task, _mock_rewrite):
        category = Category.objects.create(
            name="Ordner",
            name_de="Ordner",
            slug="translation-category",
            sw6_id="translation-category-id",
        )
        AITranslationService().queue_pending_translations()
        state = AITranslationState.objects.get(
            content_type=ContentType.objects.get_for_model(Category),
            object_id=category.pk,
            source_field="name",
            target_language="en",
        )

        with self.captureOnCommitCallbacks(execute=True):
            AITranslationService().translate_state(state_id=state.pk)

        category.refresh_from_db()
        self.assertEqual(category.name_en, "Folders")
        mock_sync_task.assert_called_once_with(category.pk)

    def test_selected_category_area_queues_category_descriptions_without_products(self):
        self.configuration.translation_areas = [AITranslationConfig.TranslationArea.CATEGORIES]
        self.configuration.record_statuses = [AITranslationConfig.RecordStatus.ACTIVE]
        self.configuration.save(update_fields=("translation_areas", "record_statuses", "updated_at"))
        category = Category.objects.create(
            name="Regale",
            name_de="Regale",
            description_de="Regale fuer das Buero.",
            slug="translation-category-description",
        )

        AITranslationService().queue_pending_translations()

        self.assertTrue(
            AITranslationState.objects.filter(
                content_type=ContentType.objects.get_for_model(Category),
                object_id=category.pk,
                source_field="description",
                target_language="en",
            ).exists()
        )
        self.assertFalse(
            AITranslationState.objects.filter(
                content_type=ContentType.objects.get_for_model(Product),
            ).exists()
        )

    def test_selected_archived_status_queues_only_archived_products(self):
        self.configuration.translation_areas = [AITranslationConfig.TranslationArea.PRODUCTS]
        self.configuration.record_statuses = [AITranslationConfig.RecordStatus.ARCHIVED]
        self.configuration.save(update_fields=("translation_areas", "record_statuses", "updated_at"))
        inactive_product = Product.objects.create(
            erp_nr="TRANS-INACTIVE",
            name="Inaktiver Tisch",
            name_de="Inaktiver Tisch",
            is_active=False,
        )
        archived_product = Product.objects.create(
            erp_nr="TRANS-ARCHIVED",
            name="Archivierter Tisch",
            name_de="Archivierter Tisch",
            is_archived=True,
        )

        AITranslationService().queue_pending_translations()

        queued_product_ids = set(
            AITranslationState.objects.filter(
                content_type=ContentType.objects.get_for_model(Product),
            ).values_list("object_id", flat=True)
        )
        self.assertEqual(queued_product_ids, {archived_product.pk})
        self.assertNotIn(inactive_product.pk, queued_product_ids)
        self.assertNotIn(self.product.pk, queued_product_ids)


class AIRewriteServiceTest(TestCase):
    def setUp(self):
        self.provider = AIProviderConfig.objects.create(name="P", model_name="gpt-5-mini", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="Schreibe um.")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")
        self.category = Category.objects.create(
            name="Buerobedarf",
            slug="buerobedarf",
            meta_description_de="Alt",
        )

    def test_create_job_is_queued_with_snapshot(self):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        self.assertEqual(job.source_snapshot, "<p>alt</p>")
        self.assertEqual(job.result_text, "")

    def test_create_category_job_is_queued_with_snapshot(self):
        job = AIRewriteService().create_job(
            category=self.category,
            field="meta_description_de",
            prompt=self.prompt,
            provider=self.provider,
        )
        self.assertIsNone(job.product)
        self.assertEqual(job.category, self.category)
        self.assertEqual(job.target, self.category)
        self.assertEqual(job.source_snapshot, "Alt")

    def test_serialize_includes_product_attributes_in_the_rewrite_language(self):
        group = PropertyGroup.objects.create(name="Material", name_de="Werkstoff")
        value = PropertyValue.objects.create(group=group, name="Karton", name_de="Pappe")
        ProductProperty.objects.create(product=self.product, value=value)

        context = AIRewriteService()._serialize(self.product, field_name="description_de")

        self.assertEqual(
            context["attributes"],
            [{"gruppe": "Werkstoff", "werte": ["Pappe"]}],
        )

    @patch(
        "ai.services.rewrite.AIProviderService.rewrite_text_with_response",
        return_value=("<p>neu</p>", '{"choices": [{"message": {"content": "<p>neu</p>"}}]}'),
    )
    def test_execute_renders_category_prompt_template_with_products_and_properties(self, mock_rewrite):
        self.prompt.system_prompt = """Kategorie: {{ category.name }}
Kategoriepfad: {{ category.get_category_path|default:'Nicht verfuegbar' }}
{% for product in category.products.all %}
Produktname: {{ product.name|default:product.erp_nr }}
Beschreibung: {{ product.description|striptags|default:product.description_short|striptags|default:'Keine Beschreibung vorhanden.' }}
Eigenschaft: {% for prop in product.product_properties.all %}{{ prop.value.group.name }}: {{ prop.value.name }}{% empty %}Keine Eigenschaften vorhanden.{% endfor %}
{% empty %}Keine Produktdaten vorhanden.{% endfor %}"""
        self.prompt.save(update_fields=["system_prompt"])
        product = Product.objects.create(
            erp_nr="P-1",
            name="",
            description="<p>Beschreibung des Produkts</p>",
        )
        product.categories.add(self.category)
        group = PropertyGroup.objects.create(name="Material")
        value = PropertyValue.objects.create(group=group, name="Karton")
        ProductProperty.objects.create(product=product, value=value)
        job = AIRewriteService().create_job(
            category=self.category,
            field="description",
            prompt=self.prompt,
            provider=self.provider,
        )

        AIRewriteService().execute(job)

        rendered_system_prompt = mock_rewrite.call_args.kwargs["system_prompt"]
        self.assertIn("Kategorie: Buerobedarf", rendered_system_prompt)
        self.assertIn("Kategoriepfad: Buerobedarf", rendered_system_prompt)
        self.assertIn("Produktname: P-1", rendered_system_prompt)
        self.assertIn("Beschreibung: Beschreibung des Produkts", rendered_system_prompt)
        self.assertIn("Eigenschaft: Material: Karton", rendered_system_prompt)
        self.assertNotIn("Keine Produktdaten vorhanden.", rendered_system_prompt)

    @patch(
        "ai.services.rewrite.AIProviderService.rewrite_text_with_response",
        return_value=("<p>neu</p>", '{"choices": [{"message": {"content": "<p>neu</p>"}}]}'),
    )
    def test_execute_sets_ready(self, _mock):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        AIRewriteService().execute(job)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.READY)
        self.assertEqual(job.result_text, "<p>neu</p>")
        self.assertIn('"choices"', job.provider_response)

    @patch("ai.services.rewrite.AIProviderService.rewrite_text_with_response", side_effect=RuntimeError("boom"))
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

    @patch("products.tasks.process_product_sync_job.delay")
    def test_apply_enqueues_product_syncs_in_target_order(self, mock_delay):
        mock_delay.return_value.id = "sync-task"
        job = AIRewriteService().create_job(
            product=self.product,
            field="description_de",
            prompt=self.prompt,
            provider=self.provider,
        )
        job.result_text = "<p>final</p>"
        job.status = AIRewriteJob.Status.READY
        job.save(update_fields=["result_text", "status"])

        with self.captureOnCommitCallbacks(execute=True):
            AIRewriteService().apply(job=job)

        self.product.refresh_from_db()
        sync_jobs = list(ProductSyncJob.objects.order_by("pk"))
        self.assertEqual(self.product.description_de, "<p>final</p>")
        self.assertEqual(
            [sync_job.target for sync_job in sync_jobs],
            [
                ProductSyncJob.Target.MICROTECH,
                ProductSyncJob.Target.SHOPWARE5,
                ProductSyncJob.Target.SHOPWARE,
            ],
        )
        self.assertEqual({tuple(sync_job.changed_fields) for sync_job in sync_jobs}, {("description_de",)})
        self.assertEqual({sync_job.trigger for sync_job in sync_jobs}, {"ai_rewrite_apply"})

    def test_apply_writes_edited_text_to_category_field(self):
        job = AIRewriteService().create_job(
            category=self.category,
            field="meta_description_de",
            prompt=self.prompt,
            provider=self.provider,
        )
        job.result_text = "Neu"
        job.status = AIRewriteJob.Status.READY
        job.save(update_fields=["result_text", "status"])
        AIRewriteService().apply(job=job)
        job.refresh_from_db(); self.category.refresh_from_db()
        self.assertEqual(self.category.meta_description_de, "Neu")
        self.assertEqual(job.status, AIRewriteJob.Status.APPLIED)


class AIRewriteTaskTest(TestCase):
    @patch(
        "ai.services.rewrite.AIProviderService.rewrite_text_with_response",
        return_value=("<p>neu</p>", '{"choices": [{"message": {"content": "<p>neu</p>"}}]}'),
    )
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
        self.category = Category.objects.create(
            name="Buerobedarf",
            slug="buerobedarf",
            meta_description_de="Alt",
        )

    def test_get_renders_with_product_and_field(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.get(url, {"product": self.product.pk, "field": "description_de"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "description_de")

    def test_get_preselects_active_prompt_and_provider(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.get(url, {"product": self.product.pk, "field": "description_de"})

        self.assertEqual(resp.context["form"].initial["prompt"], self.prompt)
        self.assertEqual(resp.context["form"].initial["provider"], self.provider)

    def test_get_renders_with_category_and_field(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.get(url, {"category": self.category.pk, "field": "meta_description_de"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kategorie")
        self.assertContains(resp, "meta_description_de")

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

    @patch("ai.admin.run_ai_rewrite_job.delay")
    def test_post_creates_category_job_and_redirects(self, mock_delay):
        mock_delay.return_value.id = "task-456"
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.post(url, {
            "category": self.category.pk,
            "field": "meta_description_de",
            "prompt": self.prompt.pk,
            "provider": self.provider.pk,
        })
        job = AIRewriteJob.objects.get()
        self.assertIsNone(job.product)
        self.assertEqual(job.category, self.category)
        self.assertEqual(job.field, "meta_description_de")
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
        self.assertContains(resp, "HTML-Quelltext")
        self.assertContains(resp, 'name="result_html"')
        self.assertContains(resp, "core/admin/ai_rewrite_wysiwyg.js")

    def test_html_source_takes_precedence_over_visual_editor(self):
        job = self._job(status=AIRewriteJob.Status.READY, result_text="<p>alt</p>")
        admin_obj = AIRewriteJobAdmin(AIRewriteJob, AdminSite())
        form_class = admin_obj.get_form(RequestFactory().get("/"), obj=job)
        form = form_class(
            data={
                "result_text": "<p>Visueller Editor</p>",
                "result_html": "<p>HTML-Quelltext</p>",
            },
            instance=job,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save(commit=False).result_text, "<p>HTML-Quelltext</p>")

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

    def test_admin_loads_extended_wysiwyg_media(self):
        admin_obj = AIRewriteJobAdmin(AIRewriteJob, AdminSite())

        self.assertIn("core/admin/ai_rewrite_wysiwyg.js", str(admin_obj.media))


class ProductFieldButtonTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin3", "a3@b.de", "pw")
        self.client.force_login(self.user)
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>x</p>")

    def test_change_view_exposes_create_link_and_field(self):
        resp = self.client.get(reverse("admin:products_product_change", args=(self.product.pk,)))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "product-ai-rewrite-fields")
        self.assertContains(resp, reverse("admin:ai_airewritejob_create"))
        self.assertContains(resp, "description_de")
        self.assertContains(resp, 'const targetParam = "product";')
        self.assertContains(resp, "createUrl.searchParams.set(targetParam, targetId);")


class CategoryFieldButtonTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin4", "a4@b.de", "pw")
        self.client.force_login(self.user)
        self.category = Category.objects.create(
            name="Buerobedarf",
            slug="buerobedarf",
            description_de="<p>x</p>",
            meta_description_de="Alt",
        )

    def test_change_view_exposes_create_link_and_rewriteable_category_fields(self):
        resp = self.client.get(reverse("admin:products_category_change", args=(self.category.pk,)))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "product-ai-rewrite-fields")
        self.assertContains(resp, reverse("admin:ai_airewritejob_create"))
        self.assertContains(resp, "description_de")
        self.assertContains(resp, "meta_description_de")
        self.assertContains(resp, 'const targetParam = "category";')
