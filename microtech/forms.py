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
    get_dataset_field_queryset_for_action_target,
    get_django_field_map,
    get_rule_action_target_choices,
    get_rule_action_target_map,
    is_dataset_field_allowed_for_action_target,
    resolve_rule_action_target,
    RULE_ACTION_TARGET_CREATE_EXTRA_POSITION,
    sync_django_field_catalog,
)


_BOOL_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off", "nein"}
LEGACY_UI_ACTION = "__legacy_set_field__"


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


def _safe_related(value):
    try:
        return value
    except Exception:
        return None


def _condition_input_attrs(
    *,
    value_kind: str,
    example: str,
    hint: str,
    input_type: str = "",
    accepts_date_only: bool = False,
    current_value: str = "",
) -> dict[str, str]:
    attrs = {
        "data-rulebuilder-value-kind": value_kind,
        "data-rulebuilder-example": example,
        "data-rulebuilder-hint": hint,
        "data-rulebuilder-input-type": input_type,
        "data-rulebuilder-accepts-date-only": "true" if accepts_date_only else "false",
        "autocomplete": "off",
    }
    if example:
        attrs["placeholder"] = example
    if hint:
        attrs["title"] = hint

    resolved_input_type = input_type or value_kind
    if accepts_date_only and resolved_input_type == "date" and ("T" in current_value or " " in current_value):
        resolved_input_type = "datetime"
    if resolved_input_type == "int":
        attrs.update({"type": "number", "step": "1", "inputmode": "numeric"})
    elif resolved_input_type == "decimal":
        attrs.update({"type": "number", "step": "any", "inputmode": "decimal"})
    elif resolved_input_type == "date":
        attrs["type"] = "date"
    elif resolved_input_type == "datetime":
        attrs["type"] = "datetime-local"
    elif value_kind == "bool":
        attrs["data-rulebuilder-bool-values"] = "true,false"
        attrs["placeholder"] = example or "true / false"

    return attrs


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
        field_map = get_django_field_map()
        selected_field_path = _to_str(
            getattr(
                MicrotechOrderRuleDjangoField.objects
                .filter(pk=int(selected_field_id), is_active=True)
                .first(),
                "field_path",
                "",
            )
        ) if selected_field_id.isdigit() else _to_str(getattr(self.instance, "django_field_path", ""))
        selected_field_def = field_map.get(selected_field_path)
        current_expected_value = _to_str(
            self.data.get(self.add_prefix("expected_value"))
            or self.initial.get("expected_value")
            or getattr(self.instance, "expected_value", "")
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
        existing_classes = str(self.fields["operator"].widget.attrs.get("class", "")).split()
        if "rulebuilder-operator-autocomplete" not in existing_classes:
            existing_classes.append("rulebuilder-operator-autocomplete")
        self.fields["operator"].widget.attrs["class"] = " ".join(existing_classes).strip()
        self.fields["operator"].widget.attrs["data-operator-autocomplete-url"] = reverse_lazy(
            "admin:microtech_orderrule_operator_autocomplete"
        )
        self.fields["operator"].widget.attrs["data-placeholder"] = "Operator suchen..."
        expected_value_help = "Vergleichswert. Format haengt vom gewaehlen Django-Feldtyp ab."
        if selected_field_def is not None:
            expected_value_help = (
                f"Wertetyp: {selected_field_def.value_kind}. "
                f"Beispiel: {selected_field_def.example or '-'}."
            )
            if selected_field_def.accepts_date_only:
                expected_value_help = (
                    f"{expected_value_help} Fuer dieses Feld reicht ein Datum im Format YYYY-MM-DD."
                )
            if selected_field_def.hint:
                expected_value_help = f"{expected_value_help} Hinweis: {selected_field_def.hint}"
            self.fields["expected_value"].widget.attrs.update(
                _condition_input_attrs(
                    value_kind=selected_field_def.value_kind,
                    example=_to_str(selected_field_def.example),
                    hint=_to_str(selected_field_def.hint),
                    input_type=_to_str(selected_field_def.input_type),
                    accepts_date_only=bool(selected_field_def.accepts_date_only),
                    current_value=current_expected_value,
                )
            )
        else:
            self.fields["expected_value"].widget.attrs.update(
                {
                    "data-rulebuilder-value-kind": "",
                    "data-rulebuilder-example": "",
                    "data-rulebuilder-hint": "",
                    "autocomplete": "off",
                }
            )
        self.fields["expected_value"].help_text = expected_value_help

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
                if (
                    getattr(field_def, "accepts_date_only", False)
                    and "T" not in expected_value
                    and " " not in expected_value
                ):
                    date.fromisoformat(expected_value)
                else:
                    datetime.fromisoformat(expected_value)
            except ValueError:
                if getattr(field_def, "accepts_date_only", False):
                    self.add_error(
                        "expected_value",
                        "Datum/Zeit muss im ISO-Format sein (YYYY-MM-DD oder YYYY-MM-DDTHH:MM:SS).",
                    )
                else:
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
    ui_action = forms.ChoiceField(
        label="Aktion",
        choices=get_rule_action_target_choices(),
        required=False,
    )

    class Meta:
        model = MicrotechOrderRuleAction
        fields = ("is_active", "priority", "action_type", "dataset", "dataset_field", "target_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action_type"].required = False
        self.fields["action_type"].widget = forms.HiddenInput()
        if "dataset" in self.fields:
            self.fields["dataset"].queryset = (
                MicrotechDatasetCatalog.objects
                .filter(is_active=True)
                .order_by("priority", "id")
            )
            self.fields["dataset"].required = False
            self.fields["dataset"].widget = forms.HiddenInput()
        self.fields["dataset_field"].required = False

        selected_dataset_field_id = _to_str(
            self.data.get(self.add_prefix("dataset_field"))
            or self.initial.get("dataset_field")
            or getattr(self.instance, "dataset_field_id", "")
        )
        selected_dataset_field = (
            MicrotechDatasetField.objects
            .filter(pk=int(selected_dataset_field_id))
            .select_related("dataset")
            .first()
        ) if selected_dataset_field_id.isdigit() else None
        selected_action_type = _to_str(
            self.data.get(self.add_prefix("action_type"))
            or self.initial.get("action_type")
            or getattr(self.instance, "action_type", "")
        )
        inferred_ui_action = resolve_rule_action_target(
            action_type=selected_action_type,
            dataset=_safe_related(getattr(self.instance, "dataset", None)),
            dataset_field=selected_dataset_field or _safe_related(getattr(self.instance, "dataset_field", None)),
        )
        has_legacy_instance_action = (
            selected_action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD
            and bool(selected_dataset_field or _safe_related(getattr(self.instance, "dataset_field", None)))
            and not inferred_ui_action
        )
        selected_ui_action = _to_str(
            self.data.get(self.add_prefix("ui_action"))
            or self.initial.get("ui_action")
            or inferred_ui_action
            or (LEGACY_UI_ACTION if has_legacy_instance_action else "")
        )
        if has_legacy_instance_action and not any(value == LEGACY_UI_ACTION for value, _label in self.fields["ui_action"].choices):
            self.fields["ui_action"].choices = (
                *self.fields["ui_action"].choices,
                (LEGACY_UI_ACTION, "Bestehende Sonderaktion behalten"),
            )
        if selected_ui_action:
            self.initial["ui_action"] = selected_ui_action

        dataset_field_queryset = (
            MicrotechDatasetField.objects
            .filter(is_active=True, dataset__is_active=True)
            .select_related("dataset")
            .order_by("dataset__priority", "dataset__name", "priority", "field_name", "id")
        ) if selected_ui_action == LEGACY_UI_ACTION else get_dataset_field_queryset_for_action_target(action_target=selected_ui_action)
        if selected_dataset_field_id.isdigit():
            dataset_field_queryset = (
                MicrotechDatasetField.objects
                .filter(Q(pk=int(selected_dataset_field_id)) | Q(pk__in=dataset_field_queryset.values("pk")))
                .select_related("dataset")
                .order_by("dataset__priority", "dataset__name", "priority", "field_name", "id")
            )
        self.fields["dataset_field"].queryset = dataset_field_queryset

        dataset_field_classes = str(self.fields["dataset_field"].widget.attrs.get("class", "")).split()
        if "rulebuilder-dataset-field-autocomplete" not in dataset_field_classes:
            dataset_field_classes.append("rulebuilder-dataset-field-autocomplete")
        self.fields["dataset_field"].widget.attrs["class"] = " ".join(dataset_field_classes).strip()
        self.fields["dataset_field"].widget.attrs["data-dataset-field-autocomplete-url"] = reverse_lazy(
            "admin:microtech_orderrule_dataset_field_autocomplete"
        )
        self.fields["dataset_field"].widget.attrs["data-action-target"] = selected_ui_action
        self.fields["dataset_field"].widget.attrs["data-placeholder"] = "Zielfeld suchen..."
        target_label = "Zielwert"
        target_help = "Wert, der durch die Aktion geschrieben oder verwendet wird."
        if selected_ui_action:
            target_def = get_rule_action_target_map().get(selected_ui_action)
            if target_def is not None:
                target_label = target_def.target_value_label or target_label
                target_help = target_def.target_value_help or target_help
            elif selected_ui_action == LEGACY_UI_ACTION:
                target_help = "Bestehende Sonderaktion ausserhalb der gefuehrten Targets. Bitte nur behalten oder bewusst umstellen."
        if selected_dataset_field is not None and selected_ui_action != RULE_ACTION_TARGET_CREATE_EXTRA_POSITION:
            field_label = _to_str(selected_dataset_field.label) or _to_str(selected_dataset_field.field_name)
            target_help = f"{target_help} Zielfeld: {field_label} ({selected_dataset_field.field_type or 'Text'})."
            self.fields["target_value"].widget.attrs["data-dataset-field-type"] = _to_str(selected_dataset_field.field_type)
            self.fields["target_value"].widget.attrs["data-dataset-field-label"] = field_label
        self.fields["target_value"].label = target_label
        self.fields["target_value"].help_text = target_help
        self.fields["target_value"].widget.attrs["data-action-target"] = selected_ui_action
        self.fields["ui_action"].help_text = "Fachliche Aktion. Danach werden nur passende Zielfelder angeboten."

    def clean(self):
        cleaned_data = super().clean()
        dataset = cleaned_data.get("dataset")
        dataset_field = cleaned_data.get("dataset_field")
        target_value = _to_str(cleaned_data.get("target_value"))
        ui_action = _to_str(cleaned_data.get("ui_action"))
        if not ui_action:
            ui_action = resolve_rule_action_target(
                action_type=_to_str(cleaned_data.get("action_type")),
                dataset=dataset,
                dataset_field=dataset_field,
            )
            cleaned_data["ui_action"] = ui_action

        if not ui_action:
            self.add_error("ui_action", "Bitte eine Aktion waehlen.")
            return cleaned_data

        target_def = get_rule_action_target_map().get(ui_action)
        if target_def is None:
            if ui_action != LEGACY_UI_ACTION:
                self.add_error("ui_action", "Unbekannte Aktion.")
                return cleaned_data

        if ui_action == LEGACY_UI_ACTION:
            cleaned_data["action_type"] = MicrotechOrderRuleAction.ActionType.SET_FIELD
            if not dataset_field:
                self.add_error("dataset_field", "Bestehende Sonderaktion braucht weiterhin ein Zielfeld.")
                return cleaned_data
            cleaned_data["dataset"] = dataset_field.dataset
            if not target_value:
                self.add_error("target_value", "Zielwert darf nicht leer sein.")
            return cleaned_data

        if ui_action == RULE_ACTION_TARGET_CREATE_EXTRA_POSITION:
            cleaned_data["action_type"] = MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION
            cleaned_data["dataset"] = None
            cleaned_data["dataset_field"] = None
            if not target_value:
                self.add_error("target_value", "ERP-Nr fuer Zusatzposition ist erforderlich.")
            return cleaned_data

        cleaned_data["action_type"] = MicrotechOrderRuleAction.ActionType.SET_FIELD
        if not dataset_field:
            self.add_error("dataset_field", "Bitte ein passendes Zielfeld waehlen.")
            return cleaned_data
        if not is_dataset_field_allowed_for_action_target(
            dataset_field=dataset_field,
            action_target=ui_action,
        ):
            self.add_error("dataset_field", "Zielfeld passt nicht zur gewaehlten fachlichen Aktion.")
            return cleaned_data

        cleaned_data["dataset"] = dataset_field.dataset
        if not target_value:
            self.add_error("target_value", "Zielwert darf nicht leer sein.")
        return cleaned_data

    def save(self, commit=True):
        self.instance.action_type = _to_str(self.cleaned_data.get("action_type"))
        self.instance.dataset = self.cleaned_data.get("dataset")
        return super().save(commit=commit)


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
