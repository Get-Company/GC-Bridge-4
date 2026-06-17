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

    class ProductTemplate(models.TextChoices):
        STANDARD = "product", _("Standard")
        SHIPPING_FREE = "product_shipping_free", _("Kostenloser Versand")
        GREEN = "product_green", _("Grün")

    internal_title = models.CharField(
        max_length=255,
        verbose_name=_("Interner Titel"),
        help_text=_("Wird nicht in der E-Mail angezeigt."),
    )
    h1 = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Hauptüberschrift"),
    )
    h1_small = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Untertitel"),
    )
    intro_text = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Einleitungstext"),
        help_text=_("HTML erlaubt. Wird zwischen Anrede und Produkt-Listing angezeigt."),
    )
    product_template = models.CharField(
        max_length=30,
        choices=ProductTemplate.choices,
        default=ProductTemplate.STANDARD,
        verbose_name=_("Produkt-Template"),
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

    def products_with_special_price_count(self) -> int:
        return self.campaign_products.filter(special_price_override__isnull=False).count()


class EmailCampaignComponent(BaseModel):
    class ComponentKey(models.TextChoices):
        HEADER_NAV = "header_nav", _("Onlineansicht & Navigation")
        LOGO = "logo", _("Logo")
        TITLE_INTRO = "title_intro", _("Ueberschrift & Einleitung")
        PRODUCTS = "products", _("Produkte")
        CONTENT_TEXT = "content_text", _("Textblock")
        BLOG = "blog_acymailing", _("Blog Auto-Content")
        CERTS_GREEN = "certs_logo_green", _("Zertifikate gruen")
        FOUR_R = "4r", _("4R Nachhaltigkeit")
        CHRISTMAS = "weihnachten", _("Weihnachten")
        CONTACT_TABLE = "contact_table", _("Kontaktformular")
        DISCLAIMER = "disclaimer", _("Disclaimer")

    DEFAULT_COMPONENTS = (
        ComponentKey.HEADER_NAV,
        ComponentKey.LOGO,
        ComponentKey.TITLE_INTRO,
        ComponentKey.PRODUCTS,
        ComponentKey.CONTACT_TABLE,
        ComponentKey.DISCLAIMER,
    )

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
        null=True,
        blank=True,
        verbose_name=_("Bibliotheks-Komponente"),
    )
    component_key = models.CharField(
        max_length=40,
        choices=ComponentKey.choices,
        verbose_name=_("Komponente"),
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Titel"),
        help_text=_("Interner Name oder Ueberschrift fuer Textbloecke."),
    )
    subtitle = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Untertitel"),
    )
    body_html = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Inhalt"),
        help_text=_("HTML erlaubt. Wird fuer bearbeitbare Text-Komponenten verwendet."),
    )
    mjml_markup = models.TextField(
        blank=True,
        default="",
        verbose_name=_("MJML Markup"),
        help_text=_("MJML Vorlage dieser Komponente. Django-Template-Variablen sind erlaubt."),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))
    enabled = models.BooleanField(default=True, verbose_name=_("Aktiviert"))

    class Meta:
        verbose_name = _("Kampagnen-Komponente")
        verbose_name_plural = _("Kampagnen-Komponenten")
        ordering = ("order", "id")

    def __str__(self) -> str:
        if self.library_component_id:
            placement = self.library_component.get_placement_display()
            return f"{self.order} – {self.library_component.name} ({placement})"
        return self.title or self.get_component_key_display()

    def get_inline_title(self) -> str:
        return f"{self.order} - {self}"


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
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))

    class Meta:
        verbose_name = _("Kampagnen-Produkt")
        verbose_name_plural = _("Kampagnen-Produkte")
        ordering = ("order", "id")
        unique_together = (("campaign", "product"),)

    def __str__(self) -> str:
        return f"{self.campaign} | {self.product}"


class EmailCampaignSalesChannel(BaseModel):
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="sales_channels",
        verbose_name=_("Kampagne"),
    )
    sales_channel = models.ForeignKey(
        "shopware.ShopwareSettings",
        on_delete=models.PROTECT,
        verbose_name=_("Sales Channel"),
    )
    enabled = models.BooleanField(default=False, verbose_name=_("Aktiviert"))

    class Meta:
        verbose_name = _("Kampagnen-Sales-Channel")
        verbose_name_plural = _("Kampagnen-Sales-Channels")
        ordering = ("-sales_channel__is_default", "sales_channel__name")
        unique_together = (("campaign", "sales_channel"),)

    def __str__(self) -> str:
        return f"{self.campaign} | {self.sales_channel}"
