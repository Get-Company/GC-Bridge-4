from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django import forms

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
)
from microtech.rule_builder import get_django_field_map, get_operator_defs


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


def _operator_choices_for_path(field_path: str, selected: str = "") -> list[tuple[str, str]]:
    field_map = get_django_field_map()
    operator_defs = get_operator_defs()
    labels = {item.code: item.name or item.code for item in operator_defs}

    field_def = field_map.get(field_path)
    allowed_codes = tuple(field_def.allowed_operator_codes) if field_def else tuple(labels.keys())
    choices = [(code, labels.get(code, code)) for code in allowed_codes]

    if selected and selected not in {code for code, _ in choices}:
        choices.append((selected, selected))
    return choices


class MicrotechOrderRuleConditionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleCondition
        fields = ("is_active", "priority", "django_field_path", "operator_code", "expected_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_path = _to_str(
            self.data.get(self.add_prefix("django_field_path"))
            or self.initial.get("django_field_path")
            or getattr(self.instance, "django_field_path", "")
        )
        selected_operator = _to_str(
            self.data.get(self.add_prefix("operator_code"))
            or self.initial.get("operator_code")
            or getattr(self.instance, "operator_code", "")
        )

        self.fields["django_field_path"].widget = forms.TextInput(
            attrs={
                "list": "microtech-django-field-paths",
                "placeholder": "z. B. payment_method oder shipping_address__country_code",
            }
        )
        self.fields["operator_code"].widget = forms.Select(
            choices=_operator_choices_for_path(selected_path, selected_operator)
        )
        self.fields["expected_value"].help_text = (
            "Freitextwert. Format haengt vom gewaehlen Django-Feldtyp ab."
        )

    def clean(self):
        cleaned_data = super().clean()
        field_path = _to_str(cleaned_data.get("django_field_path"))
        operator_code = _to_str(cleaned_data.get("operator_code"))
        expected_value = _to_str(cleaned_data.get("expected_value"))

        field_map = get_django_field_map()
        field_def = field_map.get(field_path)
        if not field_def:
            self.add_error(
                "django_field_path",
                "Unbekannter Django-Feldpfad. Bitte einen Wert aus dem Autocomplete verwenden.",
            )
            return cleaned_data

        allowed_operators = set(field_def.allowed_operator_codes)
        if operator_code not in allowed_operators:
            allowed = ", ".join(sorted(allowed_operators))
            self.add_error("operator_code", f"Operator fuer dieses Feld nicht erlaubt. Erlaubt: {allowed}.")
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


class MicrotechOrderRuleActionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleAction
        fields = ("is_active", "priority", "action_type", "dataset", "dataset_field", "target_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_dataset_id = _to_str(
            self.data.get(self.add_prefix("dataset"))
            or self.initial.get("dataset")
            or getattr(self.instance, "dataset_id", "")
        )

        self.fields["dataset"].queryset = MicrotechDatasetCatalog.objects.filter(is_active=True).order_by("priority", "id")

        if selected_dataset_id:
            self.fields["dataset_field"].queryset = (
                MicrotechDatasetField.objects
                .filter(is_active=True, dataset_id=selected_dataset_id, dataset__is_active=True)
                .select_related("dataset")
                .order_by("priority", "id")
            )
        else:
            self.fields["dataset_field"].queryset = MicrotechDatasetField.objects.none()

        self.fields["target_value"].help_text = (
            "Bei Aktionstyp 'create_extra_position' enthaelt target_value die ERP-Nr der Zusatzposition."
        )

    def clean(self):
        cleaned_data = super().clean()
        action_type = _to_str(cleaned_data.get("action_type"))
        dataset = cleaned_data.get("dataset")
        dataset_field = cleaned_data.get("dataset_field")
        target_value = _to_str(cleaned_data.get("target_value"))

        if action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD:
            if not dataset:
                self.add_error("dataset", "Dataset ist fuer set_field erforderlich.")
            if not dataset_field:
                self.add_error("dataset_field", "Dataset Feld ist fuer set_field erforderlich.")
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
