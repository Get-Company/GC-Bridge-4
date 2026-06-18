from django.db import models
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
    attributes = models.JSONField(default=dict)
    variables = models.JSONField(default=dict)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return f"{self.tag} (campaign={self.campaign_id})"
