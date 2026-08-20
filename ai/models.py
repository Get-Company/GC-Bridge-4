from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


DEFAULT_TRANSLATION_SYSTEM_PROMPT = """Du bist ein praeziser Fachuebersetzer.

Uebersetze ausschliesslich die Werte des uebergebenen JSON-Objekts. Halte dich eng und vollstaendig an den deutschen Originaltext: keine kreativen Umformulierungen, keine Ergaenzungen, keine Kuerzungen, keine SEO-Optimierung und keine Erklaerungen.

Die JSON-Schluessel sind technische Segment-IDs. Sie muessen unveraendert bleiben. Gib ausschliesslich ein JSON-Objekt mit exakt denselben Schluesseln und den uebersetzten Textwerten zurueck. Gib kein Markdown und keinen weiteren Text aus.

HTML-Markup, technische Attribute, CSS-Klassen, Styles, URLs und IDs werden ausserhalb des Modells erhalten. Menschlich lesbare Attribute wie alt, title, aria-label und placeholder koennen als Textsegmente enthalten sein. Die Segmentwerte duerfen deshalb keine HTML-Tags enthalten. HTML-Entities innerhalb eines Segmentwerts (zum Beispiel &nbsp;) muessen unveraendert erhalten bleiben.
"""

DEFAULT_TRANSLATION_USER_PROMPT_TEMPLATE = """Uebersetze die Textsegmente eines einzelnen Feldes.

Quellsprache: {{ source_language_name }} ({{ source_language }})
Zielsprache: {{ target_language_name }} ({{ target_language }})
Sprachvariante: {{ locale_instruction }}

Textsegmente (JSON):
{{ segments_json }}
"""


def default_translation_locale_instructions() -> dict[str, str]:
    """Return editable default instructions for the configured target locales."""
    return {
        "en": "Verwende die jeweils passende englische Hochsprache.",
        "ch-de": (
            "Verwende echten schweizerdeutschen Dialekt, nicht nur Schweizer Hochdeutsch. "
            "Erfinde dabei keine regionalen Eigenheiten, die im Original nicht angelegt sind."
        ),
        "it-de": (
            "Die Ausgabesprache ist zwingend Deutsch, passend fuer den suedtirolerischen Markt. "
            "Der technische Code it-de bedeutet nicht Italienisch; verwende niemals italienische Saetze."
        ),
        "it-it": "Verwende die italienische Hochsprache.",
    }


DEFAULT_TRANSLATION_AREAS = (
    "products",
    "categories",
    "variant_families",
    "properties",
)
DEFAULT_TRANSLATION_RECORD_STATUSES = (
    "active",
    "inactive",
    "archived",
)


def default_translation_areas() -> list[str]:
    """Return all currently supported customer-content areas."""
    return list(DEFAULT_TRANSLATION_AREAS)


def default_translation_record_statuses() -> list[str]:
    """Return all record statuses so existing configurations keep their scope."""
    return list(DEFAULT_TRANSLATION_RECORD_STATUSES)


class AIProviderConfig(BaseModel):
    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    name = models.CharField(max_length=120, unique=True, verbose_name=_("Name"))
    base_url = models.URLField(
        max_length=255,
        blank=True,
        default="https://api.openai.com/v1",
        verbose_name=_("Base URL"),
    )
    model_name = models.CharField(max_length=120, verbose_name=_("Modellname"))
    api_key = models.CharField(max_length=255, blank=True, default="", verbose_name=_("API-Key"))
    timeout_seconds = models.PositiveIntegerField(default=60, verbose_name=_("Timeout (Sekunden)"))
    temperature = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.70"),
        verbose_name=_("Temperature"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("KI-Provider")
        verbose_name_plural = _("KI-Provider")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.model_name})"


class AITranslationConfig(BaseModel):
    """Editable configuration for the automatic, source-hash based translations."""

    class TranslationArea(models.TextChoices):
        PRODUCTS = "products", _("Produkttexte")
        CATEGORIES = "categories", _("Kategorietexte")
        VARIANT_FAMILIES = "variant_families", _("Variantenfamilien")
        PROPERTIES = "properties", _("Eigenschaftsgruppen und -werte")

    class RecordStatus(models.TextChoices):
        ACTIVE = "active", _("Aktive Datensätze")
        INACTIVE = "inactive", _("Inaktive Datensätze")
        ARCHIVED = "archived", _("Archivierte Datensätze")

    _translation_area_by_model_label = {
        "products.product": TranslationArea.PRODUCTS,
        "products.category": TranslationArea.CATEGORIES,
        "products.productvariantfamily": TranslationArea.VARIANT_FAMILIES,
        "products.propertygroup": TranslationArea.PROPERTIES,
        "products.propertyvalue": TranslationArea.PROPERTIES,
    }

    name = models.CharField(max_length=120, unique=True, verbose_name=_("Name"))
    provider = models.ForeignKey(
        AIProviderConfig,
        on_delete=models.PROTECT,
        related_name="translation_configs",
        verbose_name=_("KI"),
    )
    source_language = models.CharField(max_length=16, default="de", verbose_name=_("Quellsprache"))
    translation_areas = models.JSONField(
        default=default_translation_areas,
        verbose_name=_("Übersetzungsbereiche"),
        help_text=_("Legt fest, welche Inhalte der Übersetzungsscan verarbeitet."),
    )
    record_statuses = models.JSONField(
        default=default_translation_record_statuses,
        verbose_name=_("Datensatzstatus"),
        help_text=_(
            "Legt fest, welche aktiven, inaktiven oder archivierten Datensätze verarbeitet werden. "
            "Datensätze ohne eigenen Status gelten als aktiv."
        ),
    )
    batch_size = models.PositiveIntegerField(
        default=100,
        verbose_name=_("Maximale Übersetzungen pro Lauf"),
        help_text=_("Begrenzt die Anzahl einzelner Feld-/Sprachübersetzungen je Scan."),
    )
    status_retention_days = models.PositiveIntegerField(
        default=30,
        verbose_name=_("Statusanzeige aufbewahren (Tage)"),
        help_text=_("Erfolgreiche und abgebrochene Status verschwinden danach aus der Liste. 0 deaktiviert dies."),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    clear_target_on_empty_source = models.BooleanField(
        default=True,
        verbose_name=_("Ziel bei leerem Quelltext leeren"),
        help_text=_("Entfernt vorhandene Zieltexte, wenn der deutsche Quelltext geleert wurde."),
    )
    system_prompt = models.TextField(
        default=DEFAULT_TRANSLATION_SYSTEM_PROMPT,
        verbose_name=_("System-Prompt"),
    )
    user_prompt_template = models.TextField(
        default=DEFAULT_TRANSLATION_USER_PROMPT_TEMPLATE,
        verbose_name=_("Benutzer-Prompt-Vorlage"),
        help_text=_(
            "Verfügbare Platzhalter: source_language, source_language_name, "
            "target_language, target_language_name, locale_instruction und segments_json."
        ),
    )
    locale_instructions = models.JSONField(
        default=default_translation_locale_instructions,
        blank=True,
        verbose_name=_("Sprachvarianten-Hinweise"),
        help_text=_("JSON-Objekt mit Sprachcode als Schlüssel und Übersetzungshinweis als Wert."),
    )

    class Meta:
        verbose_name = _("KI-Übersetzungskonfiguration")
        verbose_name_plural = _("KI-Übersetzungskonfigurationen")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("is_active",),
                condition=Q(is_active=True),
                name="ai_translation_single_active_config",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def selected_translation_areas(self) -> frozenset[str]:
        """Return valid configured areas without trusting persisted JSON blindly."""
        valid_values = set(self.TranslationArea.values)
        configured_values = self.translation_areas if isinstance(self.translation_areas, list) else []
        return frozenset(str(value) for value in configured_values if value in valid_values)

    def selected_record_statuses(self) -> frozenset[str]:
        """Return valid configured record statuses without trusting persisted JSON blindly."""
        valid_values = set(self.RecordStatus.values)
        configured_values = self.record_statuses if isinstance(self.record_statuses, list) else []
        return frozenset(str(value) for value in configured_values if value in valid_values)

    def includes_translation_model(self, model: type[models.Model]) -> bool:
        """Return whether the model belongs to one of the selected content areas."""
        area = self._translation_area_by_model_label.get(model._meta.label_lower)
        return area in self.selected_translation_areas()

    def filter_translation_queryset(self, queryset, *, model: type[models.Model]):
        """Limit a translated-model queryset to the selected record statuses."""
        selected_statuses = self.selected_record_statuses()
        if not selected_statuses:
            return queryset.none()

        field_names = {field.name for field in model._meta.get_fields()}
        has_active_flag = "is_active" in field_names
        has_archive_flag = "is_archived" in field_names
        filters: list[Q] = []

        if has_archive_flag and self.RecordStatus.ARCHIVED in selected_statuses:
            filters.append(Q(is_archived=True))

        if self.RecordStatus.ACTIVE in selected_statuses:
            active_filter = Q()
            if has_archive_flag:
                active_filter &= Q(is_archived=False)
            if has_active_flag:
                active_filter &= Q(is_active=True)
            filters.append(active_filter)

        if self.RecordStatus.INACTIVE in selected_statuses and has_active_flag:
            inactive_filter = Q(is_active=False)
            if has_archive_flag:
                inactive_filter &= Q(is_archived=False)
            filters.append(inactive_filter)

        if not filters:
            return queryset.none()

        combined_filter = filters[0]
        for current_filter in filters[1:]:
            combined_filter |= current_filter
        return queryset.filter(combined_filter)


class AITranslationGlossaryEntry(BaseModel):
    """A global mandatory translation for one source term and target language."""

    source_term = models.CharField(max_length=255, verbose_name=_("Quellbegriff"))
    target_language = models.CharField(max_length=16, verbose_name=_("Zielsprache"))
    target_term = models.CharField(max_length=255, verbose_name=_("Verbindliche Übersetzung"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("KI-Übersetzungsglossareintrag")
        verbose_name_plural = _("KI-Übersetzungsglossar")
        ordering = ("source_term", "target_language")
        indexes = [
            models.Index(fields=("target_language", "is_active")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source_term", "target_language"),
                name="ai_translation_glossary_unique_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_term} → {self.target_term} ({self.target_language})"


class AIRewritePrompt(BaseModel):
    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    slug = models.SlugField(max_length=255, unique=True, blank=True, verbose_name=_("Slug"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    system_prompt = models.TextField(verbose_name=_("Anweisung"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("KI-Rewrite-Prompt")
        verbose_name_plural = _("KI-Rewrite-Prompts")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:255]
        super().save(*args, **kwargs)


class AIRewriteJob(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("In Arbeit")
        READY = "ready", _("Ergebnis vorhanden")
        APPLIED = "applied", _("Übernommen")
        FAILED = "failed", _("Fehlgeschlagen")

    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="ai_rewrite_jobs",
        null=True,
        blank=True,
        verbose_name=_("Produkt"),
    )
    category = models.ForeignKey(
        "products.Category",
        on_delete=models.PROTECT,
        related_name="ai_rewrite_jobs",
        null=True,
        blank=True,
        verbose_name=_("Kategorie"),
    )
    field = models.CharField(max_length=120, verbose_name=_("Feld"))
    prompt = models.ForeignKey(
        AIRewritePrompt,
        on_delete=models.PROTECT,
        related_name="jobs",
        verbose_name=_("Prompt"),
    )
    provider = models.ForeignKey(
        AIProviderConfig,
        on_delete=models.PROTECT,
        related_name="jobs",
        verbose_name=_("KI"),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
        verbose_name=_("Status"),
    )
    source_snapshot = models.TextField(blank=True, default="", verbose_name=_("Quellinhalt"))
    result_text = models.TextField(blank=True, default="", verbose_name=_("Ergebnis"))
    provider_response = models.TextField(
        blank=True,
        default="",
        verbose_name=_("KI-Rückgabe (roh)"),
    )
    rendered_prompt = models.TextField(blank=True, default="", verbose_name=_("Gerenderter Prompt"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Fehler"))
    celery_task_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Celery Task-ID"))
    requested_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_ai_rewrite_jobs",
        verbose_name=_("Angefordert von"),
    )
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Übernommen am"))

    class Meta:
        verbose_name = _("KI-Rewrite-Job")
        verbose_name_plural = _("KI-Rewrite-Jobs")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("product", "field")),
            models.Index(fields=("category", "field")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(product__isnull=False, category__isnull=True)
                    | Q(product__isnull=True, category__isnull=False)
                ),
                name="ai_rewrite_job_has_one_target",
            )
        ]

    def __str__(self) -> str:
        target_type = "Produkt" if self.product_id else "Kategorie"
        target_id = self.product_id or self.category_id
        return f"#{self.pk} · {target_type} {target_id} · {self.field} · {self.get_status_display()}"

    @property
    def target(self):
        if self.product_id:
            return self.product
        if self.category_id:
            return self.category
        raise ValueError("AI Rewrite Job hat kein Zielobjekt.")


class AITranslationState(BaseModel):
    """Persistent change marker and execution state for one translated field."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Wartend")
        RUNNING = "running", _("Laufend")
        SUCCEEDED = "succeeded", _("Erfolgreich")
        FAILED = "failed", _("Fehlgeschlagen")
        CANCELLED = "cancelled", _("Abgebrochen")

    configuration = models.ForeignKey(
        AITranslationConfig,
        on_delete=models.PROTECT,
        related_name="translation_states",
        verbose_name=_("Konfiguration"),
    )
    content_type = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.CASCADE,
        related_name="ai_translation_states",
        verbose_name=_("Objekttyp"),
    )
    object_id = models.PositiveBigIntegerField(verbose_name=_("Objekt-ID"))
    source_field = models.CharField(max_length=120, verbose_name=_("Quellfeld"))
    target_language = models.CharField(max_length=16, verbose_name=_("Zielsprache"))
    source_hash = models.CharField(max_length=64, verbose_name=_("Quell-Hash"))
    configuration_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Konfigurations-Hash"),
    )
    is_archived = models.BooleanField(default=False, db_index=True, verbose_name=_("Aus Liste ausgeblendet"))
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Ausgeblendet am"))
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name=_("Status"),
    )
    attempt_count = models.PositiveIntegerField(default=0, verbose_name=_("Versuche"))
    celery_task_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Celery Task-ID"))
    translated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Übersetzt am"))
    last_error = models.TextField(blank=True, default="", verbose_name=_("Letzter Fehler"))

    class Meta:
        verbose_name = _("KI-Übersetzungsstatus")
        verbose_name_plural = _("KI-Übersetzungsstatus")
        ordering = ("status", "updated_at", "id")
        indexes = [
            models.Index(fields=("content_type", "object_id")),
            models.Index(fields=("status", "updated_at")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("content_type", "object_id", "source_field", "target_language"),
                name="ai_translation_state_unique_target",
            )
        ]

    def __str__(self) -> str:
        return f"{self.content_type} #{self.object_id} · {self.source_field} → {self.target_language}"
