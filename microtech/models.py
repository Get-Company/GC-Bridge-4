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

    class Meta:
        verbose_name = _("Microtech Bestellregel")
        verbose_name_plural = _("Microtech Bestellregeln")
        ordering = ("priority", "id")

    def __str__(self) -> str:
        return f"{self.priority} | {self.name}"


class MicrotechOrderRuleCondition(BaseModel):
    class ValueType(models.TextChoices):
        STRING = "string", _("Text")
        DECIMAL = "decimal", _("Dezimalzahl")
        ENUM = "enum", _("Enum")
        COUNTRY_CODE = "country_code", _("ISO2-Laendercode")

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
        verbose_name=_("Source Feld"),
    )
    operator = models.CharField(
        max_length=16,
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
    class ValueType(models.TextChoices):
        STRING = "string", _("Text")
        INT = "int", _("Ganzzahl")
        DECIMAL = "decimal", _("Dezimalzahl")
        BOOL = "bool", _("Bool")
        ENUM = "enum", _("Enum")

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


class MicrotechOrderRuleOperator(BaseModel):
    class EngineOperator(models.TextChoices):
        EQUALS = "eq", _("==")
        CONTAINS = "contains", _("enthaelt")
        GREATER_THAN = "gt", _(">")
        LESS_THAN = "lt", _("<")

    code = models.CharField(max_length=64, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    engine_operator = models.CharField(
        max_length=16,
        choices=EngineOperator.choices,
        default=EngineOperator.EQUALS,
        verbose_name=_("Engine Operator"),
    )
    hint = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Bestellregel Operator")
        verbose_name_plural = _("Microtech Bestellregel Operatoren")
        ordering = ("priority", "id")

    def __str__(self) -> str:
        return f"{self.priority} | {self.name} ({self.code})"


class MicrotechOrderRuleConditionSource(BaseModel):
    code = models.CharField(max_length=64, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    engine_source_field = models.CharField(
        max_length=64,
        choices=MicrotechOrderRuleCondition.SourceField.choices,
        verbose_name=_("Engine Source Feld"),
    )
    value_type = models.CharField(
        max_length=32,
        choices=MicrotechOrderRuleCondition.ValueType.choices,
        default=MicrotechOrderRuleCondition.ValueType.STRING,
        verbose_name=_("Wertetyp"),
    )
    operators = models.ManyToManyField(
        MicrotechOrderRuleOperator,
        related_name="condition_sources",
        blank=True,
        verbose_name=_("Erlaubte Operatoren"),
    )
    hint = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))
    example = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Beispiel"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Bestellregel Source Feld")
        verbose_name_plural = _("Microtech Bestellregel Source Felder")
        ordering = ("priority", "id")

    def __str__(self) -> str:
        return f"{self.priority} | {self.name} ({self.code})"


class MicrotechOrderRuleActionTarget(BaseModel):
    code = models.CharField(max_length=64, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    engine_target_field = models.CharField(
        max_length=64,
        choices=MicrotechOrderRuleAction.TargetField.choices,
        verbose_name=_("Engine Target Feld"),
    )
    value_type = models.CharField(
        max_length=32,
        choices=MicrotechOrderRuleAction.ValueType.choices,
        default=MicrotechOrderRuleAction.ValueType.STRING,
        verbose_name=_("Wertetyp"),
    )
    enum_values = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Enum Werte (kommagetrennt)"),
    )
    hint = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))
    example = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Beispiel"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Bestellregel Target Feld")
        verbose_name_plural = _("Microtech Bestellregel Target Felder")
        ordering = ("priority", "id")

    def __str__(self) -> str:
        return f"{self.priority} | {self.name} ({self.code})"
