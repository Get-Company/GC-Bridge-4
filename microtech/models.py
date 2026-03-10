import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


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

    def __str__(self) -> str:
        dataset_name = self.dataset.name if self.dataset_id else "?"
        return f"{dataset_name}.{self.field_name}"


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
