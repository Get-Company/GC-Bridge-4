from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class NewsletterRecipient(BaseModel):
    class Status(models.TextChoices):
        NOT_SET = "notSet", _("Nicht bestaetigt")
        OPT_IN = "optIn", _("Bestaetigt")
        OPT_OUT = "optOut", _("Abgemeldet")
        DIRECT = "direct", _("Direkt aktiv")

    shopware_id = models.CharField(
        max_length=36,
        unique=True,
        db_index=True,
        verbose_name=_("Shopware ID"),
    )
    customer_shopware_id = models.CharField(
        max_length=36,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Shopware Kunden-ID"),
    )
    customer = models.ForeignKey(
        "customer.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="newsletter_recipients",
        verbose_name=_("Django Kunde"),
    )
    selected_email_campaign = models.ForeignKey(
        "emails.EmailCampaign",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="selected_newsletter_recipients",
        verbose_name=_("Ausgewaehlte E-Mail Kampagne"),
        help_text=_("Diese Kampagne wird fuer die Queue-Action dieses Empfaengers gerendert."),
    )
    is_customer = models.BooleanField(default=False, db_index=True, verbose_name=_("Ist Kunde"))
    email = models.EmailField(max_length=255, db_index=True, verbose_name=_("E-Mail"))
    title = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Titel"))
    salutation_id = models.CharField(max_length=36, blank=True, default="", verbose_name=_("Anrede ID"))
    salutation_key = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Anrede Schluessel"))
    salutation_display_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Anrede"))
    salutation_letter_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Briefanrede"))
    first_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Vorname"))
    last_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Nachname"))
    zip_code = models.CharField(max_length=64, blank=True, default="", verbose_name=_("PLZ"))
    city = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Ort"))
    street = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Strasse"))
    status = models.CharField(
        max_length=64,
        choices=Status.choices,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Status"),
    )
    hash = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hash"))
    sales_channel_id = models.CharField(
        max_length=36,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Sales-Channel ID"),
    )
    language_id = models.CharField(
        max_length=36,
        blank=True,
        default="",
        verbose_name=_("Sprach-ID"),
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Bestaetigt am"))
    remote_created_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Shopware angelegt am"))
    remote_updated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Shopware aktualisiert am"))
    last_synced_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name=_("Zuletzt synchronisiert am"))
    is_present_in_shopware = models.BooleanField(default=True, db_index=True, verbose_name=_("In Shopware vorhanden"))
    custom_fields = models.JSONField(default=dict, blank=True, verbose_name=_("Custom Fields"))
    raw_data = models.JSONField(default=dict, blank=True, verbose_name=_("Shopware Rohdaten"))

    class Meta:
        verbose_name = _("Newsletter Empfaenger")
        verbose_name_plural = _("Newsletter Empfaenger")
        ordering = ("email", "last_name", "first_name")
        indexes = [
            models.Index(fields=("status", "email"), name="newsletter_status_email_idx"),
        ]

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.title, self.first_name, self.last_name) if part).strip()

    @property
    def is_active_status(self) -> bool:
        return self.status in {self.Status.DIRECT, self.Status.OPT_IN}

    def __str__(self) -> str:
        return f"{self.email} | {self.status or '-'}"
