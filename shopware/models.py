from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class ShopwareConnection(BaseModel):
    api_url = models.CharField(
        max_length=500,
        verbose_name=_("API URL"),
        help_text=_("z.B. https://mein-shop.de/api"),
    )
    client_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Client ID"))
    client_secret = models.CharField(max_length=500, blank=True, default="", verbose_name=_("Client Secret"))
    grant_type = models.CharField(
        max_length=32,
        default="resource_owner",
        choices=[
            ("resource_owner", "Resource Owner (Benutzername + Passwort)"),
            ("client_credentials", "Client Credentials (ID + Secret)"),
        ],
        verbose_name=_("Grant Type"),
    )
    username = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Benutzername"))
    password = models.CharField(max_length=500, blank=True, default="", verbose_name=_("Passwort"))

    class Meta:
        verbose_name = _("Shopware Verbindung")
        verbose_name_plural = _("Shopware Verbindung")

    def __str__(self) -> str:
        return self.api_url or "Shopware Verbindung"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "ShopwareConnection":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ShopwareSettings(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name=_("Bezeichnung"))
    sales_channel_id = models.CharField(max_length=255, blank=True, verbose_name=_("Verkaufskanal-ID"))
    tax_high_id = models.CharField(max_length=255, blank=True, verbose_name=_("Steuer-ID hoch"))
    tax_low_id = models.CharField(max_length=255, blank=True, verbose_name=_("Steuer-ID niedrig"))
    currency_id = models.CharField(max_length=255, blank=True, verbose_name=_("Waehrungs-ID"))
    rule_id_price = models.CharField(max_length=255, blank=True, verbose_name=_("Preisregel-ID"))
    price_factor = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("1.0"),
        verbose_name=_("Preisfaktor"),
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Standardkanal"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    def save(self, *args, **kwargs):
        if self.is_default:
            ShopwareSettings.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Shopware Konfiguration")
        verbose_name_plural = _("Shopware Konfigurationen")
        constraints = [
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="unique_default_sales_channel",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Shopware5Settings(BaseModel):
    is_active = models.BooleanField(
        default=False,
        verbose_name=_("Shopware 5 Sync aktiv"),
        help_text=_("Wenn aktiv, schreibt der Shopware-6-Produktsync Bestand, Preise und Aktiv-Status auch nach Shopware 5."),
    )
    api_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("API URL"),
        help_text=_("Optional. Falls leer, wird SHOPWARE5_API_URL aus der Umgebung verwendet."),
    )
    username = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("API Benutzer"),
        help_text=_("Optional. Falls leer, wird SHOPWARE5_API_USER aus der Umgebung verwendet."),
    )
    api_token = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("API Token"),
        help_text=_("Optional. Falls leer, wird SHOPWARE5_API_TOKEN aus der Umgebung verwendet."),
    )
    fail_on_error = models.BooleanField(
        default=False,
        verbose_name=_("Sync bei Shopware-5-Fehler abbrechen"),
        help_text=_("Standard: Fehler werden protokolliert, aber der Shopware-6-Sync bleibt erfolgreich."),
    )

    class Meta:
        verbose_name = _("Shopware 5 Sync")
        verbose_name_plural = _("Shopware 5 Sync")

    def __str__(self) -> str:
        return "Shopware 5 Sync"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "Shopware5Settings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
