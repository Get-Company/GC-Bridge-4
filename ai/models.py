from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


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
        verbose_name = _("AI Provider")
        verbose_name_plural = _("AI Provider")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.model_name})"


class AIRewritePrompt(BaseModel):
    class OutputFormat(models.TextChoices):
        TEXT = "text", _("Text")
        HTML = "html", _("HTML")

    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    slug = models.SlugField(max_length=255, unique=True, blank=True, verbose_name=_("Slug"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    provider = models.ForeignKey(
        AIProviderConfig,
        on_delete=models.PROTECT,
        related_name="prompts",
        verbose_name=_("Provider"),
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="ai_rewrite_prompts",
        verbose_name=_("Modell"),
    )
    source_field = models.CharField(max_length=120, verbose_name=_("Quellfeld"))
    target_field = models.CharField(max_length=120, verbose_name=_("Zielfeld"))
    system_prompt = models.TextField(verbose_name=_("System Prompt"))
    user_prompt_template = models.TextField(
        blank=True,
        default="",
        verbose_name=_("User Prompt Template"),
        help_text=_("Optional. Wenn leer, wird ein Standard-Template verwendet."),
    )
    output_format = models.CharField(
        max_length=20,
        choices=OutputFormat.choices,
        default=OutputFormat.HTML,
        verbose_name=_("Ausgabeformat"),
    )
    temperature_override = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Temperature Override"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("AI Rewrite Prompt")
        verbose_name_plural = _("AI Rewrite Prompts")
        ordering = ("name",)

    def __str__(self) -> str:
        model = self.content_type.model_class()
        model_label = model._meta.label if model else self.content_type.model
        return f"{self.name} [{model_label}:{self.target_field}]"

    def clean(self) -> None:
        super().clean()
        model = self.content_type.model_class() if self.content_type_id else None
        if model is None:
            return

        missing_fields = [
            field_name
            for field_name in (self.source_field, self.target_field)
            if field_name and not hasattr(model, field_name)
        ]
        if missing_fields:
            raise ValidationError(
                {
                    "target_field": _(
                        "Diese Felder existieren nicht auf %(model)s: %(fields)s"
                    )
                    % {
                        "model": model._meta.label,
                        "fields": ", ".join(missing_fields),
                    }
                }
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:255]
        super().save(*args, **kwargs)


class AIRewriteJob(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Entwurf")
        PENDING_REVIEW = "pending_review", _("Zur Freigabe")
        APPROVED = "approved", _("Freigegeben")
        REJECTED = "rejected", _("Abgelehnt")
        APPLIED = "applied", _("Uebernommen")
        FAILED = "failed", _("Fehlgeschlagen")

    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="ai_rewrite_jobs",
        verbose_name=_("Modell"),
    )
    object_id = models.PositiveBigIntegerField(verbose_name=_("Objekt-ID"))
    content_object = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Objekt"))
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
        verbose_name=_("Provider"),
    )
    source_field = models.CharField(max_length=120, verbose_name=_("Quellfeld"))
    target_field = models.CharField(max_length=120, verbose_name=_("Zielfeld"))
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_REVIEW,
        db_index=True,
        verbose_name=_("Status"),
    )
    source_snapshot = models.TextField(blank=True, default="", verbose_name=_("Quellinhalt"))
    rendered_prompt = models.TextField(blank=True, default="", verbose_name=_("Gerenderter Prompt"))
    result_text = models.TextField(blank=True, default="", verbose_name=_("Ergebnis"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Fehler"))
    requested_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_ai_rewrite_jobs",
        verbose_name=_("Angefordert von"),
    )
    approved_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_ai_rewrite_jobs",
        verbose_name=_("Freigegeben von"),
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Freigegeben am"))
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Uebernommen am"))

    class Meta:
        verbose_name = _("AI Rewrite Job")
        verbose_name_plural = _("AI Rewrite Jobs")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("content_type", "object_id")),
        ]

    def __str__(self) -> str:
        return f"{self.object_repr or self.content_type} · {self.target_field} · {self.get_status_display()}"
