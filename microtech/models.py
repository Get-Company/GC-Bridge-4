import uuid

from django.db import models
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from microtech.customs_fields import DEFAULT_SWISS_CUSTOMS_FIELD_DEFINITIONS


class MicrotechJob(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Wartend")
        RUNNING = "running", _("Laufend")
        SUCCEEDED = "succeeded", _("Erfolgreich")
        FAILED = "failed", _("Fehlgeschlagen")
        CANCELLED = "cancelled", _("Abgebrochen")

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True, verbose_name=_("Status")
    )
    priority = models.PositiveSmallIntegerField(default=100, db_index=True, verbose_name=_("Prioritaet"))
    label = models.CharField(max_length=255, verbose_name=_("Bezeichnung"))
    correlation_id = models.CharField(max_length=64, unique=True, db_index=True, verbose_name=_("Correlation ID"))
    started_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Gestartet"))
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Beendet"))
    last_error = models.TextField(blank=True, default="", verbose_name=_("Letzter Fehler"))

    class Meta:
        verbose_name = _("Microtech Job")
        verbose_name_plural = _("Microtech Jobs")
        ordering = ("priority", "created_at")
        indexes = [
            models.Index(fields=["status", "priority", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.label} (P{self.priority})"

    @staticmethod
    def make_correlation_id() -> str:
        return uuid.uuid4().hex[:16]


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
        return f"Microtech - Mandant {self.mandant}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MicrotechSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MicrotechSwissCustomsFieldMapping(BaseModel):
    class Section(models.TextChoices):
        SHIPMENT = "shipment", _("Sendung")
        EXPORTER_ADDRESS = "exporter_address", _("Exporteur Adresse")
        EXPORTER_CONTACT = "exporter_contact", _("Exporteur Kontakt")
        EXPORTER_CUSTOMS = "exporter_customs", _("Exporteur Zolldaten")
        IMPORTER_ADDRESS = "importer_address", _("Importeur Adresse")
        IMPORTER_CONTACT = "importer_contact", _("Importeur Kontakt")
        IMPORTER_CUSTOMS = "importer_customs", _("Importeur Zolldaten")
        CONSIGNEE_ADDRESS = "consignee_address", _("Empfaenger Adresse")
        CONSIGNEE_CONTACT = "consignee_contact", _("Empfaenger Kontakt")
        INVOICE = "invoice", _("Rechnung")
        LINE_ITEM = "line_item", _("Position")
        LINE_ITEM_PREFERENCE = "line_item_preference", _("Position Praeferenz")
        LINE_ITEM_NATIONAL_CUSTOMS = "line_item_national_customs", _("Position nationale Zolldaten")

    class SourceType(models.TextChoices):
        STATIC = "static", _("Statischer Wert")
        ORDER = "order", _("Bestellung")
        CUSTOMER = "customer", _("Kunde")
        BILLING_ADDRESS = "billing_address", _("Rechnungsadresse")
        SHIPPING_ADDRESS = "shipping_address", _("Lieferadresse")
        ORDER_DETAIL = "order_detail", _("Bestellposition")
        PRODUCT = "product", _("Produkt")
        COMPUTED = "computed", _("Berechneter Resolver")

    portal_field = models.CharField(max_length=255, unique=True, verbose_name=_("Portal Feld"))
    section = models.CharField(
        max_length=48,
        choices=Section.choices,
        default=Section.SHIPMENT,
        verbose_name=_("Bereich"),
    )
    source_type = models.CharField(
        max_length=32,
        choices=SourceType.choices,
        default=SourceType.STATIC,
        verbose_name=_("Quelltyp"),
    )
    source_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Quellpfad / Resolver"),
    )
    static_value = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Statischer Wert"))
    value_kind = models.CharField(max_length=32, blank=True, default="text", verbose_name=_("Wertetyp"))
    is_required = models.BooleanField(default=False, verbose_name=_("Pflichtfeld"))
    help_text = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Schweiz Zoll Feldmapping")
        verbose_name_plural = _("Microtech Schweiz Zoll Feldmappings")
        ordering = ("priority", "portal_field", "id")

    def __str__(self) -> str:
        return f"{self.portal_field} [{self.source_type}]"

    def save(self, *args, **kwargs):
        self.static_value = strip_tags(self.static_value or "").strip()
        super().save(*args, **kwargs)

    @property
    def source_preview(self) -> str:
        if self.source_type == self.SourceType.STATIC:
            return strip_tags(self.static_value or "").strip()
        return self.source_path

    @classmethod
    def ensure_defaults(cls) -> None:
        for priority, definition in enumerate(DEFAULT_SWISS_CUSTOMS_FIELD_DEFINITIONS, start=10):
            cls.objects.get_or_create(
                portal_field=definition.portal_field,
                defaults={
                    "section": definition.section,
                    "source_type": definition.source_type,
                    "source_path": definition.source_path,
                    "static_value": definition.static_value,
                    "value_kind": definition.value_kind,
                    "is_required": definition.is_required,
                    "help_text": definition.help_text,
                    "priority": priority,
                    "is_active": True,
                },
            )


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
    django_field = models.ForeignKey(
        "MicrotechOrderRuleDjangoField",
        on_delete=models.SET_NULL,
        related_name="rule_conditions",
        null=True,
        blank=True,
        verbose_name=_("Django Feld"),
    )
    operator = models.ForeignKey(
        "MicrotechOrderRuleOperator",
        on_delete=models.SET_NULL,
        related_name="rule_conditions",
        null=True,
        blank=True,
        verbose_name=_("Operator"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))
    django_field_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Django Feldpfad"),
    )
    operator_code = models.CharField(
        max_length=64,
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
        return f"{self.rule_id} | {self.django_field_path} {self.operator_code} {self.expected_value}"


class MicrotechDatasetCatalog(BaseModel):
    code = models.CharField(max_length=64, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=255, verbose_name=_("Dataset Name"))
    description = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Bezeichnung"))
    source_identifier = models.CharField(max_length=255, unique=True, verbose_name=_("Source Identifier"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Dataset")
        verbose_name_plural = _("Microtech Datasets")
        ordering = ("priority", "name", "id")

    def __str__(self) -> str:
        if self.description:
            return f"{self.priority} | {self.name} - {self.description}"
        return f"{self.priority} | {self.name}"


class MicrotechDatasetField(BaseModel):
    dataset = models.ForeignKey(
        MicrotechDatasetCatalog,
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name=_("Dataset"),
    )
    field_name = models.CharField(max_length=128, verbose_name=_("Feldname"))
    label = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Bezeichnung"))
    field_type = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Feldtyp"))
    is_calc_field = models.BooleanField(default=False, verbose_name=_("Berechnetes Feld"))
    can_access = models.BooleanField(default=True, verbose_name=_("Lesbar"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Dataset Feld")
        verbose_name_plural = _("Microtech Dataset Felder")
        ordering = ("dataset__priority", "dataset_id", "priority", "field_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("dataset", "field_name"),
                name="unique_microtech_dataset_field_name",
            )
        ]

    @property
    def display_label(self) -> str:
        dataset_name = self.dataset.name if self.dataset_id else "?"
        base = f"{dataset_name}.{self.field_name}"
        label = str(self.label or "").strip()
        if label:
            return f"{base} - {label}"
        return base

    def __str__(self) -> str:
        return self.display_label


class MicrotechOrderRuleAction(BaseModel):
    class ActionType(models.TextChoices):
        SET_FIELD = "set_field", _("Dataset Feld setzen")
        CREATE_EXTRA_POSITION = "create_extra_position", _("Zusatzposition anlegen")

    rule = models.ForeignKey(
        MicrotechOrderRule,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Regel"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))
    action_type = models.CharField(
        max_length=32,
        choices=ActionType.choices,
        default=ActionType.SET_FIELD,
        verbose_name=_("Aktionstyp"),
    )
    dataset = models.ForeignKey(
        MicrotechDatasetCatalog,
        on_delete=models.SET_NULL,
        related_name="rule_actions",
        null=True,
        blank=True,
        verbose_name=_("Dataset"),
    )
    dataset_field = models.ForeignKey(
        MicrotechDatasetField,
        on_delete=models.SET_NULL,
        related_name="rule_actions",
        null=True,
        blank=True,
        verbose_name=_("Dataset Feld"),
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
        if self.action_type == self.ActionType.CREATE_EXTRA_POSITION:
            return f"{self.rule_id} | create_extra_position({self.target_value})"
        field_name = self.dataset_field.field_name if self.dataset_field_id else "?"
        return f"{self.rule_id} | {field_name} = {self.target_value}"


class MicrotechOrderRuleOperator(BaseModel):
    class EngineOperator(models.TextChoices):
        EQUALS = "eq", _("==")
        NOT_EQUALS = "ne", _("!=")
        CONTAINS = "contains", _("enthaelt")
        GREATER_THAN = "gt", _(">")
        LESS_THAN = "lt", _("<")
        IS_EMPTY = "is_empty", _("ist leer")
        IS_NOT_EMPTY = "is_not_empty", _("ist nicht leer")

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
        return f"{self.name} - ({self.code})"


class MicrotechOrderRuleDjangoField(BaseModel):
    field_path = models.CharField(max_length=255, unique=True, verbose_name=_("Django Feldpfad"))
    label = models.CharField(max_length=255, verbose_name=_("Label"))
    value_kind = models.CharField(max_length=32, verbose_name=_("Wertetyp"))
    hint = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))
    example = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Beispiel"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Django Feldkatalog")
        verbose_name_plural = _("Microtech Django Feldkatalog")
        ordering = ("priority", "field_path", "id")

    def __str__(self) -> str:
        return f"{self.label} [{self.field_path}]"


class MicrotechOrderRuleDjangoFieldPolicy(BaseModel):
    field_path = models.CharField(max_length=255, unique=True, verbose_name=_("Django Feldpfad"))
    label_override = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Label Override"))
    hint = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))
    allowed_operators = models.ManyToManyField(
        MicrotechOrderRuleOperator,
        related_name="django_field_policies",
        blank=True,
        verbose_name=_("Erlaubte Operatoren"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Microtech Django Bedingungsfeld")
        verbose_name_plural = _("Microtech Django Bedingungsfelder")
        ordering = ("priority", "field_path", "id")

    def __str__(self) -> str:
        return f"{self.priority} | {self.field_path}"
