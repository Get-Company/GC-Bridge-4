from django.db import models
from django.core.exceptions import ValidationError
from core.models import BaseModel


class EmailBuilderCampaign(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        READY = "ready", "Bereit"
        EXPORTED = "exported", "Exportiert"

    internal_title = models.CharField(max_length=255, verbose_name="Interner Titel")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    global_css = models.TextField(blank=True, default="", verbose_name="Globale CSS-Regeln")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Email Kampagne (v2)"

    def __str__(self):
        return self.internal_title


class EmailBlock(BaseModel):
    campaign = models.ForeignKey(
        EmailBuilderCampaign, on_delete=models.CASCADE, related_name="blocks"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    tag = models.CharField(max_length=50)
    component = models.ForeignKey(
        "emails.MjmlComponent", null=True, blank=True, on_delete=models.PROTECT
    )
    campaign_product = models.ForeignKey(
        "EmailBuilderCampaignProduct",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blocks",
    )
    attributes = models.JSONField(default=dict)
    variables = models.JSONField(default=dict)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return f"{self.tag} (campaign={self.campaign_id})"


class EmailBuilderCampaignProduct(BaseModel):
    campaign = models.ForeignKey(
        EmailBuilderCampaign,
        on_delete=models.CASCADE,
        related_name="campaign_products",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="email_builder_campaign_products",
    )
    special_price_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Sonderpreis",
    )
    discount_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Rabatt (%)",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")
        unique_together = (("campaign", "product"),)
        verbose_name = "Email Builder Produkt"
        verbose_name_plural = "Email Builder Produkte"

    def clean(self):
        if self.special_price_override and self.discount_pct:
            raise ValidationError("Nur Sonderpreis ODER Rabatt (%) angeben, nicht beides.")

    def __str__(self):
        return f"{self.campaign} | {self.product}"
