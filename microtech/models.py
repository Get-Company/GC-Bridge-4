from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class MicrotechSettings(BaseModel):
    mandant = models.CharField(max_length=100, verbose_name=_("Mandant"))
    firma = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Firma"))
    benutzer = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Benutzer (Autosync)"))
    manual_benutzer = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Benutzer (Manuell)"))
    default_zahlungsart_id = models.PositiveIntegerField(default=22, verbose_name=_("Standard Zahlungsart-ID"))
    default_versandart_id = models.PositiveIntegerField(default=10, verbose_name=_("Standard Versandart-ID"))
    default_vorgangsart_id = models.PositiveIntegerField(default=111, verbose_name=_("Standard Vorgangsart-ID"))

    class Meta:
        verbose_name = _("Microtech Konfiguration")
        verbose_name_plural = _("Microtech Konfiguration")

    def __str__(self) -> str:
        return f"Microtech – Mandant {self.mandant}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MicrotechSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MicrotechOrderRule(BaseModel):
    class CustomerType(models.TextChoices):
        ANY = "any", _("Beliebig")
        COMPANY = "company", _("Firma")
        PRIVATE = "private", _("Privat")

    class CountryMatchMode(models.TextChoices):
        BILLING_ONLY = "billing_only", _("Nur Rechnungsland")
        SHIPPING_ONLY = "shipping_only", _("Nur Lieferland")
        EITHER = "either", _("Rechnungs- oder Lieferland")
        BOTH = "both", _("Rechnungs- und Lieferland")

    class Na1Mode(models.TextChoices):
        AUTO = "auto", _("Automatisch")
        FIRMA_OR_SALUTATION = "firma_or_salutation", _("Firma fuer Unternehmen, sonst Anrede")
        SALUTATION_ONLY = "salutation_only", _("Immer Anrede")
        STATIC = "static", _("Statischer Text")

    class PaymentPositionMode(models.TextChoices):
        FIXED = "fixed", _("Fester Betrag")
        PERCENT_TOTAL = "percent_total", _("Prozent vom Bestellwert")

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    customer_type = models.CharField(
        max_length=32,
        choices=CustomerType.choices,
        default=CustomerType.ANY,
        verbose_name=_("Kundentyp"),
    )
    billing_country_code = models.CharField(
        max_length=8,
        blank=True,
        default="",
        verbose_name=_("Rechnungsland (ISO2)"),
    )
    shipping_country_code = models.CharField(
        max_length=8,
        blank=True,
        default="",
        verbose_name=_("Lieferland (ISO2)"),
    )
    country_match_mode = models.CharField(
        max_length=32,
        choices=CountryMatchMode.choices,
        default=CountryMatchMode.EITHER,
        verbose_name=_("Laenderabgleich"),
    )
    payment_method_pattern = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Zahlungsart enthaelt"),
    )
    shipping_method_pattern = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Versandart enthaelt"),
    )

    na1_mode = models.CharField(
        max_length=32,
        choices=Na1Mode.choices,
        default=Na1Mode.AUTO,
        verbose_name=_("Na1 Modus"),
    )
    na1_static_value = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Na1 statischer Text"),
    )

    vorgangsart_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Vorgangsart-ID"),
    )
    zahlungsart_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Zahlungsart-ID"),
    )
    versandart_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Versandart-ID"),
    )
    zahlungsbedingung = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Zahlungsbedingung"),
    )

    add_payment_position = models.BooleanField(
        default=False,
        verbose_name=_("Zusatzposition fuer Zahlungsart anlegen"),
    )
    payment_position_erp_nr = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Zahlungs-Zusatzposition ERP-Nr"),
    )
    payment_position_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Zahlungs-Zusatzposition Name"),
    )
    payment_position_mode = models.CharField(
        max_length=32,
        choices=PaymentPositionMode.choices,
        default=PaymentPositionMode.FIXED,
        verbose_name=_("Zahlungs-Zusatzposition Modus"),
    )
    payment_position_value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name=_("Zahlungs-Zusatzposition Wert"),
    )

    class Meta:
        verbose_name = _("Microtech Bestellregel")
        verbose_name_plural = _("Microtech Bestellregeln")
        ordering = ("priority", "id")

    def __str__(self) -> str:
        return f"{self.priority} | {self.name}"
