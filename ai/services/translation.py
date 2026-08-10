from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from html import unescape
import hashlib
import json
import re
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template import Context, Engine
from django.utils import timezone
from loguru import logger
from modeltranslation import settings as modeltranslation_settings
from modeltranslation.translator import translator
from modeltranslation.utils import build_localized_fieldname

from ai.models import AITranslationConfig, AITranslationGlossaryEntry, AITranslationState
from core.services import BaseService
from products.models import Category, Product, ProductSyncJob
from products.services import (
    ProductAutoSyncService,
    disable_category_auto_sync,
    disable_product_auto_sync,
)

from .provider import AIProviderService


_TRANSLATABLE_FIELD_TYPES = ("CharField", "TextField")
_RAW_TEXT_TAGS = frozenset({"code", "pre", "script", "style"})
_TRANSLATION_PIPELINE_VERSION = "3"
_GLOSSARY_FUZZY_MINIMUM_RATIO = 0.88
_GLOSSARY_SHORT_TERM_FUZZY_MINIMUM_RATIO = 0.92
_GLOSSARY_MINIMUM_FUZZY_TERM_LENGTH = 5
_MANDATORY_OUTPUT_LANGUAGE_RULES = {
    "it-de": (
        "VERBINDLICHE AUSGABESPRACHE: Deutsch. Der technische Zielcode 'it-de' steht fuer Deutsch "
        "im suedtirolerischen/italienischen Markt und NICHT fuer Italienisch. Gib keine italienischen "
        "Saetze oder italienische Uebersetzung aus; Eigennamen, Marken und technische Bezeichnungen "
        "bleiben nur unveraendert, wenn sie im Original stehen."
    ),
}
_TAG_NAME_RE = re.compile(r"^<\s*(?P<closing>/)?\s*(?P<name>[A-Za-z][A-Za-z0-9:_-]*)")
_HUMAN_TEXT_ATTRIBUTE_RE = re.compile(
    r"\s(?:alt|title|aria-label|placeholder)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class TranslationSegment:
    identifier: str
    source_text: str
    attribute_quote: str | None = None


@dataclass
class SegmentedText:
    """Original markup plus the text nodes that may safely be translated."""

    parts: list[str | TranslationSegment]
    segments: list[TranslationSegment]

    def render(self, translations: dict[str, str]) -> str:
        rendered: list[str] = []
        for part in self.parts:
            if isinstance(part, str):
                rendered.append(part)
                continue
            translated = translations.get(part.identifier)
            if translated is None:
                raise ValueError(f"Antwort enthaelt kein Segment {part.identifier}.")
            # The model is never allowed to inject markup into the original HTML.
            safe_text = str(translated).replace("<", "&lt;").replace(">", "&gt;")
            if part.attribute_quote == '"':
                safe_text = safe_text.replace('"', "&quot;")
            elif part.attribute_quote == "'":
                safe_text = safe_text.replace("'", "&#x27;")
            rendered.append(safe_text)
        return "".join(rendered)


class AITranslationService(BaseService):
    """Queue and execute deterministic translations for modeltranslation fields."""

    model = AITranslationState
    product_translation_sync_targets = (
        ProductSyncJob.Target.SHOPWARE,
    )

    def __init__(self) -> None:
        super().__init__()
        self.provider_service = AIProviderService()
        self.template_engine = Engine(autoescape=False)

    def queue_pending_translations(self, *, configuration_id: int | None = None) -> list[int]:
        """Create/update state rows for changed German source fields.

        A source hash is intentionally based on the raw stored field value. This
        means even relevant whitespace or HTML changes trigger a retranslation.
        """
        configuration = self.get_active_configuration(configuration_id=configuration_id)
        if configuration is None:
            return []

        self.archive_expired_states(configuration=configuration)

        source_language = str(configuration.source_language or "").strip()
        available_languages = tuple(modeltranslation_settings.AVAILABLE_LANGUAGES)
        if source_language not in available_languages:
            raise ValueError(f"Quellsprache '{source_language}' ist nicht in django-modeltranslation angelegt.")

        target_languages = tuple(language for language in available_languages if language != source_language)
        queued_state_ids: list[int] = []
        batch_size = max(int(configuration.batch_size), 1)
        configuration_hash = self.configuration_fingerprint(configuration)

        for model, source_fields in self._iter_registered_text_models(configuration=configuration):
            if len(queued_state_ids) >= batch_size:
                break

            content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
            states = {
                (state.object_id, state.source_field, state.target_language): state
                for state in self.model.objects.filter(content_type=content_type)
            }
            localized_source_fields = {
                source_field: build_localized_fieldname(source_field, source_language)
                for source_field in source_fields
            }
            queryset = model._default_manager.only(
                "pk",
                *source_fields,
                *localized_source_fields.values(),
            ).order_by("pk")
            queryset = configuration.filter_translation_queryset(queryset, model=model)

            for instance in queryset.iterator(chunk_size=200):
                for source_field in source_fields:
                    source_value = self._source_value_for_field(
                        target=instance,
                        source_field=source_field,
                        source_language=source_language,
                    )
                    source_hash = self.source_hash(source_value)
                    for target_language in target_languages:
                        if len(queued_state_ids) >= batch_size:
                            break
                        state = states.get((instance.pk, source_field, target_language))
                        state_id = self._queue_state_if_needed(
                            configuration=configuration,
                            content_type=content_type,
                            object_id=instance.pk,
                            source_field=source_field,
                            target_language=target_language,
                            source_value=source_value,
                            source_hash=source_hash,
                            configuration_hash=configuration_hash,
                            state=state,
                        )
                        if state_id is not None:
                            queued_state_ids.append(state_id)
                    if len(queued_state_ids) >= batch_size:
                        break

        return queued_state_ids

    def archive_expired_states(self, *, configuration: AITranslationConfig) -> int:
        """Hide terminal state rows while retaining their source/configuration hashes."""
        retention_days = max(int(configuration.status_retention_days or 0), 0)
        if not retention_days:
            return 0

        now = timezone.now()
        cutoff = now - timedelta(days=retention_days)
        expired_statuses = (
            Q(status=self.model.Status.SUCCEEDED, translated_at__lt=cutoff)
            | Q(status=self.model.Status.SUCCEEDED, translated_at__isnull=True, updated_at__lt=cutoff)
            | Q(status=self.model.Status.CANCELLED, updated_at__lt=cutoff)
        )
        return self.model.objects.filter(
            configuration=configuration,
            is_archived=False,
        ).filter(expired_statuses).update(
            is_archived=True,
            archived_at=now,
            updated_at=now,
        )

    def get_active_configuration(self, *, configuration_id: int | None = None) -> AITranslationConfig | None:
        configurations = AITranslationConfig.objects.filter(is_active=True).select_related("provider")
        if configuration_id is not None:
            return configurations.filter(pk=configuration_id).first()
        return configurations.order_by("pk").first()

    def translate_state(self, *, state_id: int) -> AITranslationState | None:
        """Translate one state without holding a database lock during the AI call."""
        with transaction.atomic():
            state = (
                self.model.objects.select_for_update()
                .select_related("configuration__provider", "content_type")
                .filter(pk=state_id)
                .first()
            )
            if state is None:
                return None
            if state.status not in (self.model.Status.PENDING, self.model.Status.FAILED):
                return state
            if not state.configuration.is_active:
                return self._cancel_state(state, "Die Uebersetzungskonfiguration ist nicht aktiv.")

            target = self._get_target(state)
            if target is None:
                return self._cancel_state(state, "Das zugehoerige Objekt existiert nicht mehr.")

            source_value = self._source_value(target, state)
            current_source_hash = self.source_hash(source_value)
            current_configuration_hash = self.configuration_fingerprint(state.configuration)
            if current_source_hash != state.source_hash or current_configuration_hash != state.configuration_hash:
                state.source_hash = current_source_hash
                state.configuration_hash = current_configuration_hash

            state.status = self.model.Status.RUNNING
            state.attempt_count += 1
            state.last_error = ""
            state.save(
                update_fields=(
                    "source_hash", "configuration_hash", "status", "attempt_count", "last_error", "updated_at",
                )
            )
            processing_source_hash = state.source_hash
            processing_configuration_hash = state.configuration_hash

        try:
            if not source_value:
                result = "" if state.configuration.clear_target_on_empty_source else None
            else:
                segmented = self.segment_html_text(source_value)
                translations = self._translate_segments(state=state, segments=segmented.segments)
                result = segmented.render(translations)
        except Exception as exc:  # noqa: BLE001 - failure is persisted for the task dashboard.
            return self._mark_failed(state_id=state_id, error=str(exc))

        with transaction.atomic():
            state = (
                self.model.objects.select_for_update()
                .select_related("configuration__provider", "content_type")
                .get(pk=state_id)
            )
            target = self._get_target(state, lock=True)
            if target is None:
                return self._cancel_state(state, "Das zugehoerige Objekt existiert nicht mehr.")

            current_source_value = self._source_value(target, state)
            current_source_hash = self.source_hash(current_source_value)
            current_configuration_hash = self.configuration_fingerprint(state.configuration)
            if (
                state.source_hash != processing_source_hash
                or current_source_hash != processing_source_hash
                or state.configuration_hash != processing_configuration_hash
                or current_configuration_hash != processing_configuration_hash
            ):
                state.source_hash = current_source_hash
                state.configuration_hash = current_configuration_hash
                state.status = self.model.Status.PENDING
                state.last_error = "Quelltext oder Uebersetzungskonfiguration hat sich waehrend der Verarbeitung geaendert."
                state.save(
                    update_fields=("source_hash", "configuration_hash", "status", "last_error", "updated_at")
                )
                return state

            if result is not None:
                target_field = build_localized_fieldname(state.source_field, state.target_language)
                if self._field_value(target, target_field) != result:
                    setattr(target, target_field, result)
                    if isinstance(target, Product):
                        # A regular Product.save() queues all default targets.
                        # Translation fields are SW6-only content, so write them
                        # to that system explicitly instead.
                        with disable_product_auto_sync():
                            target.save(update_fields=(target_field, "updated_at"))
                        self._enqueue_product_translation_sync(
                            product_id=target.pk,
                            target_field=target_field,
                        )
                    elif isinstance(target, Category):
                        # AI translations retain their dedicated lightweight
                        # SW6 write-back below. Suppress the generic category
                        # content signal so the same translation is not sent
                        # twice and product assignments are not re-read.
                        with disable_category_auto_sync():
                            target.save(update_fields=(target_field, "updated_at"))
                        self._enqueue_category_translation_sync(category_id=target.pk)
                    else:
                        target.save(update_fields=(target_field, "updated_at"))

            state.status = self.model.Status.SUCCEEDED
            state.translated_at = timezone.now()
            state.last_error = ""
            state.save(update_fields=("status", "translated_at", "last_error", "updated_at"))
            return state

    def _enqueue_product_translation_sync(self, *, product_id: int, target_field: str) -> None:
        """Schedule only the Shopware systems after a product translation."""

        def enqueue_after_commit() -> None:
            ProductAutoSyncService().enqueue_product_sync(
                product_id=product_id,
                changed_fields=[target_field],
                trigger="ai_translation",
                targets=self.product_translation_sync_targets,
            )

        transaction.on_commit(enqueue_after_commit)

    @staticmethod
    def _enqueue_category_translation_sync(*, category_id: int) -> None:
        """Schedule the isolated SW6 category-translation payload after commit."""

        def enqueue_after_commit() -> None:
            from products.tasks import sync_category_translations_to_shopware

            try:
                sync_category_translations_to_shopware.delay(category_id)
            except Exception as exc:  # noqa: BLE001 - keep the completed translation when dispatch is unavailable.
                logger.warning(
                    "Could not enqueue Shopware category translation sync for category {}: {}",
                    category_id,
                    exc,
                )

        transaction.on_commit(enqueue_after_commit)

    @classmethod
    def source_hash(cls, source_value: str) -> str:
        return hashlib.sha256(source_value.encode("utf-8")).hexdigest()

    @staticmethod
    def configuration_fingerprint(configuration: AITranslationConfig) -> str:
        """Return the configuration parts that can change a translation result."""
        provider = configuration.provider
        glossary_entries = list(
            configuration.glossary_entries.filter(is_active=True)
            .order_by("target_language", "source_term", "pk")
            .values("source_term", "target_language", "target_term")
        )
        payload = {
            "translation_pipeline_version": _TRANSLATION_PIPELINE_VERSION,
            "source_language": configuration.source_language,
            "translation_areas": sorted(configuration.selected_translation_areas()),
            "record_statuses": sorted(configuration.selected_record_statuses()),
            "clear_target_on_empty_source": configuration.clear_target_on_empty_source,
            "system_prompt": configuration.system_prompt,
            "user_prompt_template": configuration.user_prompt_template,
            "locale_instructions": configuration.locale_instructions or {},
            "glossary_entries": glossary_entries,
            "provider_id": configuration.provider_id,
            "provider_model_name": provider.model_name,
            "provider_base_url": provider.base_url,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def segment_html_text(cls, source_value: str) -> SegmentedText:
        """Keep every markup byte and expose only visible text nodes to the model."""
        parts: list[str | TranslationSegment] = []
        segments: list[TranslationSegment] = []
        raw_text_tags: list[str] = []
        position = 0

        while position < len(source_value):
            next_tag_start = source_value.find("<", position)
            if next_tag_start < 0:
                cls._append_text_part(
                    source_value[position:],
                    parts=parts,
                    segments=segments,
                    protected=bool(raw_text_tags),
                )
                break

            if next_tag_start > position:
                cls._append_text_part(
                    source_value[position:next_tag_start],
                    parts=parts,
                    segments=segments,
                    protected=bool(raw_text_tags),
                )

            tag_end = cls._find_tag_end(source_value, next_tag_start)
            if tag_end is None:
                cls._append_text_part(
                    source_value[next_tag_start:],
                    parts=parts,
                    segments=segments,
                    protected=bool(raw_text_tags),
                )
                break

            candidate = source_value[next_tag_start:tag_end + 1]
            tag_info = cls._get_tag_info(candidate)
            if tag_info is None and not candidate.startswith(("<!--", "<!", "<?")):
                cls._append_text_part(
                    candidate,
                    parts=parts,
                    segments=segments,
                    protected=bool(raw_text_tags),
                )
                position = tag_end + 1
                continue

            if tag_info is not None:
                tag_name, is_closing, is_self_closing = tag_info
                if not is_closing:
                    cls._append_markup_part(candidate, parts=parts, segments=segments)
                else:
                    parts.append(candidate)
                if is_closing and raw_text_tags and raw_text_tags[-1] == tag_name:
                    raw_text_tags.pop()
                elif tag_name in _RAW_TEXT_TAGS and not is_self_closing:
                    raw_text_tags.append(tag_name)
            else:
                parts.append(candidate)
            position = tag_end + 1

        return SegmentedText(parts=parts, segments=segments)

    def _queue_state_if_needed(
        self,
        *,
        configuration: AITranslationConfig,
        content_type: ContentType,
        object_id: int,
        source_field: str,
        target_language: str,
        source_value: str,
        source_hash: str,
        configuration_hash: str,
        state: AITranslationState | None,
    ) -> int | None:
        if state is not None:
            if (
                state.source_hash == source_hash
                and state.configuration_hash == configuration_hash
                and state.status == self.model.Status.SUCCEEDED
            ):
                return None
            if (
                state.source_hash == source_hash
                and state.configuration_hash == configuration_hash
                and state.status == self.model.Status.RUNNING
            ):
                return None

        if not source_value and state is None:
            return None

        if state is None:
            try:
                state, created = self.model.objects.get_or_create(
                    content_type=content_type,
                    object_id=object_id,
                    source_field=source_field,
                    target_language=target_language,
                    defaults={
                        "configuration": configuration,
                        "source_hash": source_hash,
                        "configuration_hash": configuration_hash,
                        "status": self.model.Status.PENDING,
                    },
                )
                if (
                    not created
                    and state.source_hash == source_hash
                    and state.configuration_hash == configuration_hash
                    and state.status in (self.model.Status.SUCCEEDED, self.model.Status.RUNNING)
                ):
                    return None
            except IntegrityError:
                state = self.model.objects.get(
                    content_type=content_type,
                    object_id=object_id,
                    source_field=source_field,
                    target_language=target_language,
                )
                if (
                    state.source_hash == source_hash
                    and state.configuration_hash == configuration_hash
                    and state.status in (self.model.Status.SUCCEEDED, self.model.Status.RUNNING)
                ):
                    return None

        if not source_value and not configuration.clear_target_on_empty_source:
            state.configuration = configuration
            state.source_hash = source_hash
            state.configuration_hash = configuration_hash
            state.is_archived = False
            state.archived_at = None
            state.status = self.model.Status.SUCCEEDED
            state.translated_at = timezone.now()
            state.last_error = "Quelltext ist leer; Zieltext wurde gemaess Konfiguration beibehalten."
            state.save(
                update_fields=(
                    "configuration", "source_hash", "configuration_hash", "is_archived", "archived_at", "status", "translated_at", "last_error", "updated_at",
                )
            )
            return None

        state.configuration = configuration
        state.source_hash = source_hash
        state.configuration_hash = configuration_hash
        state.is_archived = False
        state.archived_at = None
        state.status = self.model.Status.PENDING
        state.celery_task_id = ""
        state.last_error = ""
        state.save(
            update_fields=(
                "configuration", "source_hash", "configuration_hash", "is_archived", "archived_at", "status", "celery_task_id", "last_error", "updated_at",
            )
        )
        return state.pk

    def _translate_segments(
        self,
        *,
        state: AITranslationState,
        segments: list[TranslationSegment],
    ) -> dict[str, str]:
        if not segments:
            return {}

        configuration = state.configuration
        glossary_entries = self._relevant_glossary_entries(
            configuration=configuration,
            target_language=state.target_language,
            segments=segments,
        )
        context = self._prompt_context(configuration=configuration, target_language=state.target_language, segments=segments)
        system_prompt = self.template_engine.from_string(configuration.system_prompt).render(Context(context)).strip()
        user_prompt = self.template_engine.from_string(configuration.user_prompt_template).render(Context(context)).strip()
        glossary_instruction = self._glossary_instruction(glossary_entries)
        if glossary_instruction:
            system_prompt = f"{system_prompt}\n\n{glossary_instruction}".strip()
        mandatory_language_rule = self._mandatory_output_language_rule(state.target_language)
        if mandatory_language_rule:
            system_prompt = f"{system_prompt}\n\n{mandatory_language_rule}".strip()
            user_prompt = f"{user_prompt}\n\n{mandatory_language_rule}".strip()
        response, _provider_response = self.provider_service.rewrite_text_with_response(
            provider=configuration.provider,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return self._parse_translation_response(response=response, expected_segments=segments)

    @classmethod
    def _relevant_glossary_entries(
        cls,
        *,
        configuration: AITranslationConfig,
        target_language: str,
        segments: list[TranslationSegment],
    ) -> list[AITranslationGlossaryEntry]:
        """Return only the active terms that occur in this translation request."""
        source_tokens = cls._glossary_tokens(" ".join(segment.source_text for segment in segments))
        if not source_tokens:
            return []

        entries = configuration.glossary_entries.filter(
            is_active=True,
            target_language=target_language,
        ).only("pk", "source_term", "target_language", "target_term")
        matching_entries = [
            entry
            for entry in entries
            if cls._glossary_entry_matches(entry.source_term, source_tokens)
        ]
        return sorted(
            matching_entries,
            key=lambda entry: (-len(cls._normalize_glossary_text(entry.source_term)), entry.source_term.casefold()),
        )

    @staticmethod
    def _normalize_glossary_text(value: str) -> str:
        """Normalize punctuation and whitespace so spelling variants still match."""
        normalized = unescape(str(value)).casefold()
        normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
        return " ".join(normalized.split())

    @classmethod
    def _glossary_tokens(cls, value: str) -> list[str]:
        normalized = cls._normalize_glossary_text(value)
        return normalized.split() if normalized else []

    @classmethod
    def _glossary_entry_matches(cls, source_term: str, source_tokens: list[str]) -> bool:
        term_tokens = cls._glossary_tokens(source_term)
        if not term_tokens:
            return False
        if cls._contains_token_sequence(source_tokens, term_tokens):
            return True

        normalized_term = " ".join(term_tokens)
        if len(normalized_term) < _GLOSSARY_MINIMUM_FUZZY_TERM_LENGTH:
            return False

        minimum_ratio = (
            _GLOSSARY_SHORT_TERM_FUZZY_MINIMUM_RATIO
            if len(normalized_term) < 10
            else _GLOSSARY_FUZZY_MINIMUM_RATIO
        )
        minimum_window_size = max(1, len(term_tokens) - 1)
        maximum_window_size = min(len(source_tokens), len(term_tokens) + 1)
        term_token_set = set(term_tokens)

        for window_size in range(minimum_window_size, maximum_window_size + 1):
            for start in range(len(source_tokens) - window_size + 1):
                candidate_tokens = source_tokens[start:start + window_size]
                if len(term_tokens) > 1 and not term_token_set.intersection(candidate_tokens):
                    continue
                candidate = " ".join(candidate_tokens)
                if SequenceMatcher(None, normalized_term, candidate, autojunk=False).ratio() >= minimum_ratio:
                    return True
        return False

    @staticmethod
    def _contains_token_sequence(source_tokens: list[str], term_tokens: list[str]) -> bool:
        last_start = len(source_tokens) - len(term_tokens)
        return any(
            source_tokens[start:start + len(term_tokens)] == term_tokens
            for start in range(last_start + 1)
        )

    @staticmethod
    def _glossary_instruction(entries: list[AITranslationGlossaryEntry]) -> str:
        if not entries:
            return ""
        glossary_json = json.dumps(
            [
                {"Quelle": entry.source_term, "Uebersetzung": entry.target_term}
                for entry in entries
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            "VERBINDLICHES GLOSSAR: Die folgenden Eintraege wurden im aktuellen Text erkannt. "
            "Verwende ihre Uebersetzungen exakt und lasse sie gegenueber allgemeinen Begriffen Vorrang haben. "
            "Wenn sich Eintraege ueberlappen, hat der spezifischere (laengere) Begriff Vorrang.\n"
            f"{glossary_json}"
        )

    @staticmethod
    def _parse_translation_response(
        *,
        response: str,
        expected_segments: list[TranslationSegment],
    ) -> dict[str, str]:
        response = response.strip()
        if response.startswith("```") and response.endswith("```"):
            response = response.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError("Das Modell hat kein gueltiges JSON-Objekt geliefert.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Das Modell hat kein JSON-Objekt geliefert.")

        expected_ids = {segment.identifier for segment in expected_segments}
        if set(parsed.keys()) != expected_ids:
            raise ValueError("Die Segment-IDs der Modellantwort stimmen nicht mit dem Quelltext ueberein.")
        if any(not isinstance(value, str) for value in parsed.values()):
            raise ValueError("Alle Uebersetzungssegmente muessen Textwerte sein.")
        return {str(identifier): str(value) for identifier, value in parsed.items()}

    @staticmethod
    def _append_text_part(
        value: str,
        *,
        parts: list[str | TranslationSegment],
        segments: list[TranslationSegment],
        protected: bool,
        attribute_quote: str | None = None,
    ) -> None:
        if protected or not value:
            parts.append(value)
            return

        leading_length = len(value) - len(value.lstrip())
        trailing_length = len(value) - len(value.rstrip())
        if leading_length:
            parts.append(value[:leading_length])
        middle_end = len(value) - trailing_length if trailing_length else len(value)
        middle = value[leading_length:middle_end]
        if middle:
            segment = TranslationSegment(
                identifier=f"T{len(segments) + 1:04d}",
                source_text=middle,
                attribute_quote=attribute_quote,
            )
            parts.append(segment)
            segments.append(segment)
        if trailing_length:
            parts.append(value[middle_end:])

    @classmethod
    def _append_markup_part(
        cls,
        value: str,
        *,
        parts: list[str | TranslationSegment],
        segments: list[TranslationSegment],
    ) -> None:
        """Translate only explicitly human-readable HTML attribute values."""
        position = 0
        for match in _HUMAN_TEXT_ATTRIBUTE_RE.finditer(value):
            value_start, value_end = match.span("value")
            parts.append(value[position:value_start])
            cls._append_text_part(
                match.group("value"),
                parts=parts,
                segments=segments,
                protected=False,
                attribute_quote=match.group("quote"),
            )
            position = value_end
        parts.append(value[position:])

    @staticmethod
    def _find_tag_end(value: str, start: int) -> int | None:
        quote: str | None = None
        for position in range(start + 1, len(value)):
            character = value[position]
            if quote:
                if character == quote:
                    quote = None
                continue
            if character in {"'", '"'}:
                quote = character
            elif character == ">":
                return position
        return None

    @staticmethod
    def _get_tag_info(value: str) -> tuple[str, bool, bool] | None:
        match = _TAG_NAME_RE.match(value)
        if match is None:
            return None
        return (
            match.group("name").lower(),
            bool(match.group("closing")),
            value.rstrip().endswith("/>") or value.startswith("<!"),
        )

    def _prompt_context(
        self,
        *,
        configuration: AITranslationConfig,
        target_language: str,
        segments: list[TranslationSegment],
    ) -> dict[str, Any]:
        locale_instructions = configuration.locale_instructions or {}
        if not isinstance(locale_instructions, dict):
            locale_instructions = {}
        return {
            "source_language": configuration.source_language,
            "source_language_name": self._language_name(configuration.source_language),
            "target_language": target_language,
            "target_language_name": self._language_name(target_language),
            "locale_instruction": str(
                locale_instructions.get(
                    target_language,
                    "Verwende die fuer die Zielsprache uebliche Hochsprache.",
                )
            ),
            "segments_json": json.dumps(
                {segment.identifier: segment.source_text for segment in segments},
                ensure_ascii=False,
                indent=2,
            ),
        }

    @staticmethod
    def _language_name(language_code: str) -> str:
        return str(dict(settings.LANGUAGES).get(language_code, language_code))

    @staticmethod
    def _mandatory_output_language_rule(target_language: str) -> str:
        return _MANDATORY_OUTPUT_LANGUAGE_RULES.get(target_language, "")

    @classmethod
    def _iter_registered_text_models(cls, *, configuration: AITranslationConfig | None = None):
        seen_models: set[type] = set()
        for model in translator.get_registered_models(abstract=False):
            if model._meta.abstract or model._meta.proxy or model in seen_models:
                continue
            if configuration is not None and not configuration.includes_translation_model(model):
                continue
            options = translator.get_options_for_model(model)
            source_fields = []
            for field_name in options.all_fields:
                field = model._meta.get_field(field_name)
                if field.get_internal_type() in _TRANSLATABLE_FIELD_TYPES:
                    source_fields.append(field_name)
            if source_fields:
                seen_models.add(model)
                yield model, tuple(source_fields)

    @staticmethod
    def _field_value(instance, field_name: str) -> str:
        value = instance.get(field_name, "") if isinstance(instance, dict) else getattr(instance, field_name, "")
        return "" if value is None else str(value)

    def _source_value(self, target, state: AITranslationState) -> str:
        return self._source_value_for_field(
            target=target,
            source_field=state.source_field,
            source_language=state.configuration.source_language,
        )

    @classmethod
    def _source_value_for_field(cls, *, target, source_field: str, source_language: str) -> str:
        localized_field = build_localized_fieldname(source_field, source_language)
        localized_value = cls._field_value(target, localized_field)
        if localized_value or source_language != settings.MODELTRANSLATION_DEFAULT_LANGUAGE:
            return localized_value

        # Modeltranslation adds the localized German columns after older rows
        # may already exist. Their original, non-localized database column still
        # contains the customer-visible German text. Use it until the German
        # source column has been filled, otherwise newly registered fields such
        # as variant-family content would be treated as empty.
        return cls._field_value(target.__dict__, source_field)

    @staticmethod
    def _get_target(state: AITranslationState, *, lock: bool = False):
        model = state.content_type.model_class()
        if model is None:
            return None
        queryset = model._default_manager
        if lock:
            queryset = queryset.select_for_update()
        return queryset.filter(pk=state.object_id).first()

    def _mark_failed(self, *, state_id: int, error: str) -> AITranslationState:
        with transaction.atomic():
            state = self.model.objects.select_for_update().get(pk=state_id)
            state.status = self.model.Status.FAILED
            state.last_error = error
            state.save(update_fields=("status", "last_error", "updated_at"))
            return state

    def _cancel_state(self, state: AITranslationState, error: str) -> AITranslationState:
        state.status = self.model.Status.CANCELLED
        state.last_error = error
        state.save(update_fields=("status", "last_error", "updated_at"))
        return state
