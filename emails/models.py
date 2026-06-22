from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class MjmlComponent(BaseModel):
    class Placement(models.TextChoices):
        HEAD = "head", _("Head (Kopfbereich)")
        BODY = "body", _("Body (Inhaltsbereich)")

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    mjml_markup = models.TextField(blank=True, default="", verbose_name=_("MJML-Markup"))
    placement = models.CharField(
        max_length=10,
        choices=Placement.choices,
        default=Placement.BODY,
        verbose_name=_("Platzierung"),
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Standard"))
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))
    detected_variables = models.JSONField(
        default=list, blank=True, verbose_name=_("Erkannte Variablen")
    )
    variable_labels = models.JSONField(
        default=dict, blank=True, verbose_name=_("Variablen-Labels")
    )
    default_variables = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Standard-Variablen"),
        help_text=_("Key-Value-Paare fuer Platzhalter. Werden in Kampagnen ueberschrieben."),
    )

    class Meta:
        verbose_name = _("MJML Komponente")
        verbose_name_plural = _("MJML Komponenten")
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name


class EmailCampaign(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Entwurf")
        READY = "ready", _("Bereit")
        EXPORTED = "exported", _("Exportiert")

    internal_title = models.CharField(
        max_length=255,
        verbose_name=_("Interner Titel"),
        help_text=_("Wird nicht in der E-Mail angezeigt."),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_("Status"),
    )

    class Meta:
        verbose_name = _("E-Mail Kampagne")
        verbose_name_plural = _("E-Mail Kampagnen")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.internal_title


class EmailCampaignComponent(BaseModel):
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="components",
        verbose_name=_("Kampagne"),
    )
    library_component = models.ForeignKey(
        "MjmlComponent",
        on_delete=models.PROTECT,
        related_name="campaign_usages",
        verbose_name=_("Bibliotheks-Komponente"),
    )
    campaign_product = models.ForeignKey(
        "EmailCampaignProduct",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="components",
        verbose_name=_("Produkt"),
        help_text=_("Optionales Produkt fuer Produkt-Komponenten."),
    )
    variables = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Variablen"),
        help_text=_('Key-Value-Paare fuer Platzhalter im MJML-Template, z.B. {"titel": "Hallo"}'),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))
    enabled = models.BooleanField(default=True, verbose_name=_("Aktiviert"))

    class Meta:
        verbose_name = _("Kampagnen-Komponente")
        verbose_name_plural = _("Kampagnen-Komponenten")
        ordering = ("order", "id")

    def __str__(self) -> str:
        placement = self.library_component.get_placement_display()
        return f"{self.order} – {self.library_component.name} ({placement})"

    def get_inline_title(self) -> str:
        return str(self)


class EmailCampaignProduct(BaseModel):
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="campaign_products",
        verbose_name=_("Kampagne"),
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="email_campaign_products",
        verbose_name=_("Produkt"),
    )
    special_price_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis"),
        help_text=_("Überschreibt den Sonderpreis des Produkts für diese Kampagne."),
    )
    discount_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Rabatt (%)"),
        help_text=_("Alternativ zum absoluten Sonderpreis. Wird auf den Standardkanalpreis angewendet."),
    )
    prices_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Preise synchronisiert am"),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))

    class Meta:
        verbose_name = _("Kampagnen-Produkt")
        verbose_name_plural = _("Kampagnen-Produkte")
        ordering = ("order", "id")
        unique_together = (("campaign", "product"),)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.special_price_override and self.discount_pct:
            raise ValidationError(_("Nur Sonderpreis ODER Rabatt (%) angeben, nicht beides."))

    def __str__(self) -> str:
        return f"{self.campaign} | {self.product}"

