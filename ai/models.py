from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
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
    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    slug = models.SlugField(max_length=255, unique=True, blank=True, verbose_name=_("Slug"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    system_prompt = models.TextField(verbose_name=_("Anweisung"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("AI Rewrite Prompt")
        verbose_name_plural = _("AI Rewrite Prompts")
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
        APPLIED = "applied", _("Uebernommen")
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
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Uebernommen am"))

    class Meta:
        verbose_name = _("AI Rewrite Job")
        verbose_name_plural = _("AI Rewrite Jobs")
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
