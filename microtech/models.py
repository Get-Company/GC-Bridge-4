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

    class ConditionLogic(models.TextChoices):
        ALL = "all", _("UND (&)")
        ANY = "any", _("ODER (||)")

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))
    condition_logic = models.CharField(
        max_length=16,
        choices=ConditionLogic.choices,
        default=ConditionLogic.ALL,
        verbose_name=_("Bedingungslogik"),
    )

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


class MicrotechOrderRuleCondition(BaseModel):
    class SourceField(models.TextChoices):
        CUSTOMER_TYPE = "customer_type", _("Kundentyp")
        BILLING_COUNTRY_CODE = "billing_country_code", _("Rechnungsland (ISO2)")
        SHIPPING_COUNTRY_CODE = "shipping_country_code", _("Lieferland (ISO2)")
        PAYMENT_METHOD = "payment_method", _("Zahlungsart")
        SHIPPING_METHOD = "shipping_method", _("Versandart")
        ORDER_TOTAL = "order_total", _("Bestellwert gesamt")
        ORDER_TOTAL_TAX = "order_total_tax", _("Steuer gesamt")
        SHIPPING_COSTS = "shipping_costs", _("Versandkosten")
        ORDER_NUMBER = "order_number", _("Bestellnummer")

    class Operator(models.TextChoices):
        EQUALS = "eq", _("==")
        CONTAINS = "contains", _("enthaelt")
        GREATER_THAN = "gt", _(">")
        LESS_THAN = "lt", _("<")

    rule = models.ForeignKey(
        MicrotechOrderRule,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Regel"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))
    source_field = models.CharField(
        max_length=64,
        choices=SourceField.choices,
        verbose_name=_("Source Feld"),
    )
    operator = models.CharField(
        max_length=16,
        choices=Operator.choices,
        default=Operator.EQUALS,
        verbose_name=_("Operator"),
    )
    expected_value = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Vergleichswert"),
    )

    class Meta:
        verbose_name = _("Microtech Bestellregel Bedingung")
        verbose_name_plural = _("Microtech Bestellregel Bedingungen")
        ordering = ("rule", "priority", "id")

    def __str__(self) -> str:
        return f"{self.rule_id} | {self.source_field} {self.operator} {self.expected_value}"


class MicrotechOrderRuleAction(BaseModel):
    class TargetField(models.TextChoices):
        NA1_MODE = "na1_mode", _("Na1 Modus")
        NA1_STATIC_VALUE = "na1_static_value", _("Na1 statischer Text")
        VORGANGSART_ID = "vorgangsart_id", _("Vorgangsart-ID")
        ZAHLUNGSART_ID = "zahlungsart_id", _("Zahlungsart-ID")
        VERSANDART_ID = "versandart_id", _("Versandart-ID")
        ZAHLUNGSBEDINGUNG = "zahlungsbedingung", _("Zahlungsbedingung")
        ADD_PAYMENT_POSITION = "add_payment_position", _("Zusatzposition Zahlungsart anlegen")
        PAYMENT_POSITION_ERP_NR = "payment_position_erp_nr", _("Zahlungs-Zusatzposition ERP-Nr")
        PAYMENT_POSITION_NAME = "payment_position_name", _("Zahlungs-Zusatzposition Name")
        PAYMENT_POSITION_MODE = "payment_position_mode", _("Zahlungs-Zusatzposition Modus")
        PAYMENT_POSITION_VALUE = "payment_position_value", _("Zahlungs-Zusatzposition Wert")

    rule = models.ForeignKey(
        MicrotechOrderRule,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Regel"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))
    target_field = models.CharField(
        max_length=64,
        choices=TargetField.choices,
        verbose_name=_("Target Feld"),
    )
    target_value = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Zielwert"),
    )

    class Meta:
        verbose_name = _("Microtech Bestellregel Aktion")
        verbose_name_plural = _("Microtech Bestellregel Aktionen")
        ordering = ("rule", "priority", "id")

    def __str__(self) -> str:
        return f"{self.rule_id} | {self.target_field} = {self.target_value}"
