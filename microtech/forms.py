from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Q
from django.urls import reverse_lazy

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleOperator,
)
from microtech.rule_builder import (
    get_allowed_operator_codes,
    get_django_field_map,
    sync_django_field_catalog,
)


_BOOL_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off", "nein"}


def _to_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_decimal(value: str) -> Decimal | None:
    text = _to_str(value)
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _normalize_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _parse_bool_text(value: str) -> str | None:
    normalized = _to_str(value).lower()
    if normalized in _BOOL_TRUE_VALUES:
        return "true"
    if normalized in _BOOL_FALSE_VALUES:
        return "false"
    return None


class MicrotechOrderRuleConditionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleCondition
        fields = ("is_active", "priority", "django_field", "operator", "expected_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sync_django_field_catalog()
        if not getattr(self.instance, "django_field_id", None) and getattr(self.instance, "django_field_path", ""):
            selected_catalog = (
                MicrotechOrderRuleDjangoField.objects
                .filter(field_path=self.instance.django_field_path, is_active=True)
                .first()
            )
            if selected_catalog:
                self.initial["django_field"] = selected_catalog.pk
        if not getattr(self.instance, "operator_id", None) and getattr(self.instance, "operator_code", ""):
            selected_operator = (
                MicrotechOrderRuleOperator.objects
                .filter(code=self.instance.operator_code, is_active=True)
                .first()
            )
            if selected_operator:
                self.initial["operator"] = selected_operator.pk

        selected_field_id = _to_str(
            self.data.get(self.add_prefix("django_field"))
            or self.initial.get("django_field")
            or getattr(self.instance, "django_field_id", "")
        )
        allowed_operator_codes = get_allowed_operator_codes(
            django_field_id=int(selected_field_id),
        ) if selected_field_id.isdigit() else set()
        selected_operator_id = _to_str(
            self.data.get(self.add_prefix("operator"))
            or self.initial.get("operator")
            or getattr(self.instance, "operator_id", "")
        )
        operator_queryset = MicrotechOrderRuleOperator.objects.filter(is_active=True)
        if allowed_operator_codes:
            operator_queryset = operator_queryset.filter(code__in=allowed_operator_codes)
        else:
            operator_queryset = operator_queryset.none()
        if selected_operator_id.isdigit():
            operator_queryset = (
                MicrotechOrderRuleOperator.objects
                .filter(Q(pk=int(selected_operator_id)) | Q(pk__in=operator_queryset.values("pk")))
                .order_by("priority", "id")
            )
        else:
            operator_queryset = operator_queryset.order_by("priority", "id")
        self.fields["operator"].queryset = operator_queryset
        self.fields["operator"].widget.attrs["class"] = " ".join(
            part for part in (
                self.fields["operator"].widget.attrs.get("class", ""),
                "rulebuilder-operator-autocomplete",
            ) if part
        )
        self.fields["operator"].widget.attrs["data-operator-autocomplete-url"] = reverse_lazy(
            "admin:microtech_orderrule_operator_autocomplete"
        )
        self.fields["operator"].widget.attrs["data-placeholder"] = "Operator suchen..."
        self.fields["expected_value"].help_text = (
            "Freitextwert. Format haengt vom gewaehlen Django-Feldtyp ab."
        )

    def clean(self):
        cleaned_data = super().clean()
        selected_field = cleaned_data.get("django_field")
        selected_operator = cleaned_data.get("operator")
        field_path = _to_str(getattr(selected_field, "field_path", ""))
        cleaned_data["django_field_path"] = field_path
        operator_code = _to_str(getattr(selected_operator, "code", ""))
        cleaned_data["operator_code"] = operator_code
        expected_value = _to_str(cleaned_data.get("expected_value"))

        if not selected_field or not field_path:
            self.add_error(
                "django_field",
                "Unbekannter Django-Feldpfad. Bitte einen Wert aus dem Autocomplete verwenden.",
            )
            return cleaned_data

        field_map = get_django_field_map()
        field_def = field_map.get(field_path)
        if not field_def:
            self.add_error("django_field", "Unbekannter Django-Feldpfad. Bitte einen Wert aus dem Autocomplete verwenden.")
            return cleaned_data

        if not selected_operator or not operator_code:
            self.add_error("operator", "Unbekannter Operator. Bitte einen Wert aus dem Autocomplete verwenden.")
            return cleaned_data
        allowed_operator_codes = get_allowed_operator_codes(field_path=field_path)
        if operator_code not in allowed_operator_codes:
            self.add_error("operator", "Operator ist fuer diesen Django-Feldtyp nicht erlaubt.")
            return cleaned_data

        value_kind = field_def.value_kind
        if value_kind in {"int", "decimal"}:
            parsed = _parse_decimal(expected_value)
            if parsed is None:
                self.add_error("expected_value", "Vergleichswert muss eine Zahl sein (z. B. 100 oder 100.50).")
                return cleaned_data
            cleaned_data["expected_value"] = _normalize_decimal(parsed)
            return cleaned_data

        if value_kind == "bool":
            parsed_bool = _parse_bool_text(expected_value)
            if parsed_bool is None:
                self.add_error("expected_value", "Erlaubte Bool-Werte: true/false, ja/nein, 1/0.")
                return cleaned_data
            cleaned_data["expected_value"] = parsed_bool
            return cleaned_data

        if value_kind == "date":
            try:
                date.fromisoformat(expected_value)
            except ValueError:
                self.add_error("expected_value", "Datum muss im ISO-Format sein (YYYY-MM-DD).")
                return cleaned_data
            return cleaned_data

        if value_kind == "datetime":
            try:
                datetime.fromisoformat(expected_value)
            except ValueError:
                self.add_error("expected_value", "DateTime muss im ISO-Format sein (YYYY-MM-DDTHH:MM:SS).")
                return cleaned_data
            return cleaned_data

        cleaned_data["expected_value"] = expected_value
        return cleaned_data

    def save(self, commit=True):
        self.instance.django_field_path = _to_str(self.cleaned_data.get("django_field_path"))
        self.instance.operator_code = _to_str(self.cleaned_data.get("operator_code"))
        return super().save(commit=commit)


class MicrotechOrderRuleActionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleAction
        fields = ("is_active", "priority", "action_type", "dataset", "dataset_field", "target_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "dataset" in self.fields:
            self.fields["dataset"].queryset = (
                MicrotechDatasetCatalog.objects
                .filter(is_active=True)
                .order_by("priority", "id")
            )
            self.fields["dataset"].required = False
            self.fields["dataset"].widget = forms.HiddenInput()
        self.fields["dataset_field"].queryset = (
            MicrotechDatasetField.objects
            .filter(is_active=True, dataset__is_active=True)
            .select_related("dataset")
            .order_by("dataset__priority", "dataset__name", "priority", "field_name", "id")
        )

        self.fields["target_value"].help_text = (
            "Bei Aktionstyp 'create_extra_position' enthaelt target_value die ERP-Nr der Zusatzposition."
        )
        self.fields["dataset_field"].help_text = (
            "Suche ueber alle aktiven Dataset-Felder. Das Dataset wird automatisch aus der Auswahl abgeleitet."
        )

    def clean(self):
        cleaned_data = super().clean()
        action_type = _to_str(cleaned_data.get("action_type"))
        dataset = cleaned_data.get("dataset")
        dataset_field = cleaned_data.get("dataset_field")
        target_value = _to_str(cleaned_data.get("target_value"))

        if action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD:
            if not dataset_field:
                self.add_error("dataset_field", "Dataset Feld ist fuer set_field erforderlich.")
                return cleaned_data
            if not dataset:
                dataset = dataset_field.dataset
                cleaned_data["dataset"] = dataset
            if dataset and dataset_field and dataset_field.dataset_id != dataset.id:
                self.add_error("dataset_field", "Dataset Feld passt nicht zum gewaehlten Dataset.")
            if not target_value:
                self.add_error("target_value", "Zielwert darf fuer set_field nicht leer sein.")
            return cleaned_data

        if action_type == MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION:
            if dataset:
                self.add_error("dataset", "Dataset muss bei create_extra_position leer bleiben.")
            if dataset_field:
                self.add_error("dataset_field", "Dataset Feld muss bei create_extra_position leer bleiben.")
            if not target_value:
                self.add_error("target_value", "ERP-Nr fuer Zusatzposition ist erforderlich.")
            return cleaned_data

        self.add_error("action_type", "Unbekannter Aktionstyp.")
        return cleaned_data


def condition_example_for_field(field_path: str) -> str:
    field_def = get_django_field_map().get(field_path)
    if not field_def:
        return "-"
    return _to_str(field_def.example) or "-"


__all__ = [
    "MicrotechOrderRuleActionForm",
    "MicrotechOrderRuleConditionForm",
    "condition_example_for_field",
]
