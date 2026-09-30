from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class MjmlComponent(BaseModel):
    class Placement(models.TextChoices):
        HEAD = "head", _("Head (Kopfbereich)")
        BODY = "body", _("Body (Inhaltsbereich)")

    class RenderingMode(models.TextChoices):
        DJANGO_JINJA = "jinja", _("Django/Jinja rendern")
        SHOPWARE = "shopware", _("Unverändert an Shopware weitergeben")

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    mjml_markup = models.TextField(blank=True, default="", verbose_name=_("MJML-Markup"))
    rendering_mode = models.CharField(
        max_length=20,
        choices=RenderingMode.choices,
        default=RenderingMode.DJANGO_JINJA,
        verbose_name=_("Rendering-Modus"),
        help_text=_(
            "Django/Jinja rendert Standard-Variablen. Der Shopware-Modus gibt das Markup "
            "einschließlich Shopware-Platzhaltern unverändert weiter."
        ),
    )
    placement = models.CharField(
        max_length=10,
        choices=Placement.choices,
        default=Placement.BODY,
        verbose_name=_("Platzierung"),
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Standard"))
    order = models.PositiveIntegerField(default=0, db_index=True, verbose_name=_("Reihenfolge"))
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
        help_text=_(
            "Key-Value-Paare für Django/Jinja-Platzhalter. Werden in Kampagnen "
            "überschrieben und im Shopware-Modus nicht verwendet."
        ),
    )

    class Meta:
        verbose_name = _("MJML-Komponente")
        verbose_name_plural = _("MJML-Komponenten")
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name


class EmailCampaignCategory(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name=_("Name"))

    class Meta:
        verbose_name = _("E-Mail-Kategorie")
        verbose_name_plural = _("E-Mail-Kategorien")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class EmailCampaign(BaseModel):
    class LayoutMode(models.TextChoices):
        COMPONENTS = "components", _("Komponenten (bisheriger Aufbau)")
        SIMPLE = "simple", _("Einfacher Editor")
        VISUAL = "visual", _("Visueller MJML-Editor")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Entwurf (inaktiv)")
        READY = "ready", _("Bereit (aktiv)")
        EXPORTED = "exported", _("Exportiert (inaktiv)")

    internal_title = models.CharField(
        max_length=255,
        verbose_name=_("Interner Titel"),
        help_text=_("Wird nicht in der E-Mail angezeigt."),
    )
    subject = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Betreff"),
        help_text=_("Wird als Betreff der versendeten Newsletter-E-Mail verwendet."),
    )
    layout_mode = models.CharField(
        max_length=20, choices=LayoutMode.choices, default=LayoutMode.SIMPLE
    )
    editor_content = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_("Status"),
        help_text=_(
            "Entwurf ist inaktiv. Bereit aktiviert die Kampagne für die automatische "
            "Versand-Queue. Exportiert kennzeichnet eine abgeschlossene oder extern "
            "verwendete Kampagne und ist ebenfalls inaktiv."
        ),
    )
    send_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Sendedatum"),
    )
    categories = models.ManyToManyField(
        EmailCampaignCategory,
        blank=True,
        related_name="campaigns",
        verbose_name=_("Kategorien"),
    )
    preview_recipient = models.ForeignKey(
        "newsletter.NewsletterRecipient",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="preview_campaigns",
        verbose_name=_("Vorschau-Empfänger"),
        help_text=_(
            "Dieser Newsletter-Empfänger liefert die Platzhalterdaten für Vorschau und Export."
        ),
    )
    shopware_price_activation_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
        verbose_name=_("SW6-Preisaktivierung"),
    )
    shopware_prices_activated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("SW6-Preise aktiviert am"),
    )

    class Meta:
        verbose_name = _("E-Mail-Kampagne")
        verbose_name_plural = _("E-Mail-Kampagnen")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.internal_title

    def clean(self) -> None:
        super().clean()
        if self.status != self.Status.READY:
            return
        errors = {}
        if not self.subject.strip():
            errors["subject"] = _("Für eine aktive Kampagne ist ein Betreff erforderlich.")
        if self.send_at is None:
            errors["send_at"] = _("Für eine aktive Kampagne ist ein Sendedatum erforderlich.")
        if errors:
            raise ValidationError(errors)


class EmailSmtpSettings(BaseModel):
    class Security(models.TextChoices):
        STARTTLS = "starttls", _("STARTTLS")
        SSL = "ssl", _("SSL/TLS")
        NONE = "none", _("Keine")

    is_active = models.BooleanField(
        default=False,
        verbose_name=_("Für Newsletter-Versand aktiviert"),
        help_text=_("Der spätere Versand-Worker darf diese Konfiguration nur aktiviert verwenden."),
    )
    host = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("SMTP-Server"),
        help_text=_("Zum Beispiel smtp.office365.com"),
    )
    port = models.PositiveIntegerField(
        default=587,
        validators=(MinValueValidator(1), MaxValueValidator(65535)),
        verbose_name=_("SMTP-Port"),
    )
    security = models.CharField(
        max_length=16,
        choices=Security.choices,
        default=Security.STARTTLS,
        verbose_name=_("Verschlüsselung"),
    )
    username = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Benutzername"),
    )
    password = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("Passwort"),
    )
    sender_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Absendername"),
    )
    sender_email = models.EmailField(
        blank=True,
        default="",
        verbose_name=_("Absenderadresse"),
    )
    reply_to_email = models.EmailField(
        blank=True,
        default="",
        verbose_name=_("Antwortadresse"),
        help_text=_("Optional. Ohne Angabe wird die Absenderadresse verwendet."),
    )
    timeout = models.PositiveSmallIntegerField(
        default=30,
        validators=(MinValueValidator(1), MaxValueValidator(300)),
        verbose_name=_("Timeout in Sekunden"),
    )

    class Meta:
        verbose_name = _("SMTP-Einstellungen")
        verbose_name_plural = _("SMTP-Einstellungen")

    def __str__(self) -> str:
        return "SMTP-Einstellungen"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "EmailSmtpSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def smtp_is_configured(self) -> bool:
        credentials_complete = bool(self.username) == bool(self.password)
        return bool(self.host and self.sender_email and credentials_complete)

    @property
    def effective_reply_to_email(self) -> str:
        return self.reply_to_email or self.sender_email

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if bool(self.username) != bool(self.password):
            message = _("SMTP-Benutzername und SMTP-Passwort müssen gemeinsam gepflegt werden.")
            errors["username"] = message
            errors["password"] = message
        if not self.host and any((self.username, self.password, self.sender_email)):
            errors["host"] = _("Für die SMTP-Konfiguration ist ein SMTP-Server erforderlich.")
        if self.host and not self.sender_email:
            errors["sender_email"] = _("Bitte eine SMTP-Absenderadresse hinterlegen.")
        if self.is_active and not self.smtp_is_configured:
            errors["is_active"] = _(
                "Die SMTP-Konfiguration muss vollständig sein, bevor sie aktiviert werden kann."
            )
        if errors:
            raise ValidationError(errors)


class EmailCampaignQueueEntry(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Wartet")
        SENDING = "sending", _("Wird gesendet")
        SENT = "sent", _("Gesendet")
        FAILED = "failed", _("Fehler")
        CANCELLED = "cancelled", _("Abgebrochen")

    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.PROTECT,
        related_name="queue_entries",
        verbose_name=_("Kampagne"),
    )
    recipient = models.ForeignKey(
        "newsletter.NewsletterRecipient",
        on_delete=models.PROTECT,
        related_name="email_queue_entries",
        verbose_name=_("Newsletter-Empfänger"),
    )
    customer = models.ForeignKey(
        "customer.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_queue_entries",
        verbose_name=_("Kunde"),
    )
    email = models.EmailField(max_length=255, db_index=True, verbose_name=_("E-Mail"))
    subject = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Betreff"))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
        verbose_name=_("Status"),
    )
    rendered_mjml = models.TextField(blank=True, default="", verbose_name=_("Gerendertes MJML"))
    rendered_html = models.TextField(blank=True, default="", verbose_name=_("Gerendertes HTML"))
    rendered_text = models.TextField(blank=True, default="", verbose_name=_("Gerenderter Text"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Fehlermeldung"))
    queued_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Eingereiht am"))
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Gesendet am"))

    class Meta:
        verbose_name = _("E-Mail-Warteschlangen-Eintrag")
        verbose_name_plural = _("E-Mail-Warteschlange")
        ordering = ("-queued_at",)
        indexes = [
            models.Index(fields=("status", "queued_at"), name="email_queue_status_queued_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.email} | {self.campaign} | {self.status}"


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
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Übergeordnete Komponente"),
        help_text=_("Optional für verschachtelte MJML-Strukturen."),
    )
    campaign_product = models.ForeignKey(
        "EmailCampaignProduct",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="components",
        verbose_name=_("Produkt"),
        help_text=_("Optionales Produkt für Produkt-Komponenten."),
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="email_campaign_components",
        verbose_name=_("Produkt"),
        help_text=_("Optionales Produkt für diese Kampagnen-Komponente."),
    )
    title = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Titel"))
    variables = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Variablen"),
        help_text=_('Key-Value-Paare für Platzhalter im MJML-Template, z. B. {"titel": "Hallo"}'),
    )
    order = models.PositiveIntegerField(default=0, db_index=True, verbose_name=_("Reihenfolge"))
    enabled = models.BooleanField(default=True, verbose_name=_("Aktiviert"))

    class Meta:
        verbose_name = _("Kampagnen-Komponente")
        verbose_name_plural = _("Kampagnen-Komponenten")
        ordering = ("order", "id")

    def __str__(self) -> str:
        placement = self.library_component.get_placement_display()
        title = self.title or self.library_component.name
        return f"{self.order} – {title} ({placement})"

    def get_inline_title(self) -> str:
        return str(self)

    def clean(self):
        super().clean()
        errors = {}

        if not self.parent_id:
            if errors:
                raise ValidationError(errors)
            return

        if self.pk and self.parent_id == self.pk:
            errors["parent"] = _("Eine Komponente kann nicht ihr eigener Parent sein.")

        if self.parent and self.parent.campaign_id != self.campaign_id:
            errors["parent"] = _("Parent und Child müssen zur selben Kampagne gehören.")

        seen_ids = {self.pk} if self.pk else set()
        parent = self.parent
        while parent is not None:
            if parent.pk in seen_ids:
                errors["parent"] = _("Diese Parent-Auswahl erzeugt eine Schleife.")
                break
            seen_ids.add(parent.pk)
            parent = parent.parent

        if errors:
            raise ValidationError(errors)


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
    order = models.PositiveIntegerField(default=0, db_index=True, verbose_name=_("Reihenfolge"))

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


class EmailCampaignPriceState(BaseModel):
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="applied_price_states",
        verbose_name=_("Preisführende Kampagne"),
    )
    product = models.OneToOneField(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="email_campaign_price_state",
        verbose_name=_("Produkt"),
    )
    price_snapshot = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Preiszustand vor der Kampagne"),
        help_text=_(
            "Interner Wiederherstellungszustand für entfernte oder geänderte Kampagnen-Produkte."
        ),
    )

    class Meta:
        verbose_name = _("Kampagnen-Preiszustand")
        verbose_name_plural = _("Kampagnen-Preiszustände")

    def __str__(self) -> str:
        return f"{self.campaign} | {self.product}"
