from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition
from microtech.rule_builder import get_action_target_map, get_condition_source_map, get_operator_defs


_BOOL_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off", "nein"}
_CUSTOMER_TYPE_ALIASES = {
    "firma": MicrotechOrderRule.CustomerType.COMPANY,
    "company": MicrotechOrderRule.CustomerType.COMPANY,
    "unternehmen": MicrotechOrderRule.CustomerType.COMPANY,
    "privat": MicrotechOrderRule.CustomerType.PRIVATE,
    "private": MicrotechOrderRule.CustomerType.PRIVATE,
    "any": MicrotechOrderRule.CustomerType.ANY,
    "beliebig": MicrotechOrderRule.CustomerType.ANY,
}


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


def _source_choices(selected: str = "") -> list[tuple[str, str]]:
    source_map = get_condition_source_map()
    choices = [(item.code, item.name or item.code) for item in source_map.values()]
    if selected and selected not in {code for code, _ in choices}:
        choices.append((selected, selected))
    return choices


def _operator_choices_for_source(source_code: str, selected: str = "") -> list[tuple[str, str]]:
    source_map = get_condition_source_map()
    operator_defs = get_operator_defs()
    all_ops = {item.code: item.name or item.code for item in operator_defs}
    source_def = source_map.get(source_code)
    allowed_codes = tuple(source_def.allowed_operator_codes) if source_def else tuple(all_ops.keys())
    choices = [(code, all_ops.get(code, code)) for code in allowed_codes]
    if selected and selected not in {code for code, _ in choices}:
        choices.append((selected, selected))
    return choices


def _target_choices(selected: str = "") -> list[tuple[str, str]]:
    target_map = get_action_target_map()
    choices = [(item.code, item.name or item.code) for item in target_map.values()]
    if selected and selected not in {code for code, _ in choices}:
        choices.append((selected, selected))
    return choices


class MicrotechOrderRuleConditionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleCondition
        fields = ("is_active", "priority", "source_field", "operator", "expected_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_source = _to_str(
            self.data.get(self.add_prefix("source_field"))
            or self.initial.get("source_field")
            or getattr(self.instance, "source_field", "")
        )
        selected_operator = _to_str(
            self.data.get(self.add_prefix("operator"))
            or self.initial.get("operator")
            or getattr(self.instance, "operator", "")
        )

        self.fields["source_field"].widget = forms.Select(
            choices=_source_choices(selected_source)
        )
        self.fields["operator"].widget = forms.Select(
            choices=_operator_choices_for_source(selected_source, selected_operator)
        )
        self.fields["expected_value"].help_text = (
            "Hinweise und Beispiele werden ueber Rulebuilder-Source-Felder gepflegt."
        )

    def clean(self):
        cleaned_data = super().clean()
        source_code = _to_str(cleaned_data.get("source_field"))
        operator_code = _to_str(cleaned_data.get("operator"))
        expected_value = _to_str(cleaned_data.get("expected_value"))
        source_map = get_condition_source_map()
        source_def = source_map.get(source_code)
        if not source_def:
            self.add_error("source_field", "Unbekanntes Source-Feld. Bitte in Rulebuilder-Source-Felder anlegen.")
            return cleaned_data

        allowed_operators = set(source_def.allowed_operator_codes)
        if allowed_operators and operator_code not in allowed_operators:
            allowed = ", ".join(sorted(allowed_operators))
            self.add_error("operator", f"Operator fuer dieses Source-Feld nicht erlaubt. Erlaubt: {allowed}.")
            return cleaned_data

        value_type = source_def.value_type
        if value_type == MicrotechOrderRuleCondition.ValueType.DECIMAL:
            parsed = _parse_decimal(expected_value)
            if parsed is None:
                self.add_error("expected_value", "Vergleichswert muss eine Dezimalzahl sein (z. B. 100.50).")
                return cleaned_data
            cleaned_data["expected_value"] = _normalize_decimal(parsed)
            return cleaned_data

        if value_type == MicrotechOrderRuleCondition.ValueType.COUNTRY_CODE:
            if not expected_value:
                self.add_error("expected_value", "Vergleichswert darf nicht leer sein (z. B. DE).")
                return cleaned_data
            cleaned_data["expected_value"] = expected_value.upper()
            return cleaned_data

        if source_def.engine_source_field == MicrotechOrderRuleCondition.SourceField.CUSTOMER_TYPE:
            normalized = _CUSTOMER_TYPE_ALIASES.get(expected_value.lower(), "")
            if not normalized:
                self.add_error("expected_value", "Erlaubte Werte: private, company, any.")
                return cleaned_data
            cleaned_data["expected_value"] = normalized
            return cleaned_data

        cleaned_data["expected_value"] = expected_value
        return cleaned_data


class MicrotechOrderRuleActionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleAction
        fields = ("is_active", "priority", "target_field", "target_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_target = _to_str(
            self.data.get(self.add_prefix("target_field"))
            or self.initial.get("target_field")
            or getattr(self.instance, "target_field", "")
        )
        self.fields["target_field"].widget = forms.Select(
            choices=_target_choices(selected_target)
        )
        self.fields["target_value"].help_text = (
            "Hinweise und Wertetypen werden ueber Rulebuilder-Target-Felder gepflegt."
        )

    def clean(self):
        cleaned_data = super().clean()
        target_code = _to_str(cleaned_data.get("target_field"))
        target_value = _to_str(cleaned_data.get("target_value"))
        target_map = get_action_target_map()
        target_def = target_map.get(target_code)
        if not target_def:
            self.add_error("target_field", "Unbekanntes Target-Feld. Bitte in Rulebuilder-Target-Felder anlegen.")
            return cleaned_data

        value_type = target_def.value_type
        if value_type == MicrotechOrderRuleAction.ValueType.INT:
            try:
                parsed = int(target_value)
            except (TypeError, ValueError):
                self.add_error("target_value", "Zielwert muss eine positive Ganzzahl sein.")
                return cleaned_data
            if parsed <= 0:
                self.add_error("target_value", "Zielwert muss groesser als 0 sein.")
                return cleaned_data
            cleaned_data["target_value"] = str(parsed)
            return cleaned_data

        if value_type == MicrotechOrderRuleAction.ValueType.DECIMAL:
            parsed_decimal = _parse_decimal(target_value)
            if parsed_decimal is None:
                self.add_error("target_value", "Zielwert muss eine Dezimalzahl sein (z. B. 2.50).")
                return cleaned_data
            cleaned_data["target_value"] = _normalize_decimal(parsed_decimal)
            return cleaned_data

        if value_type == MicrotechOrderRuleAction.ValueType.BOOL:
            normalized = target_value.lower()
            if normalized in _BOOL_TRUE_VALUES:
                cleaned_data["target_value"] = "true"
                return cleaned_data
            if normalized in _BOOL_FALSE_VALUES:
                cleaned_data["target_value"] = "false"
                return cleaned_data
            self.add_error("target_value", "Erlaubte Bool-Werte: true/false, ja/nein, 1/0.")
            return cleaned_data

        if value_type == MicrotechOrderRuleAction.ValueType.ENUM:
            allowed_values = set(target_def.enum_values)
            if target_value not in allowed_values:
                allowed = ", ".join(sorted(allowed_values))
                self.add_error("target_value", f"Ungueltiger Enum-Wert. Erlaubt: {allowed}.")
                return cleaned_data
            return cleaned_data

        cleaned_data["target_value"] = target_value
        return cleaned_data


def condition_example_for_field(source_code: str) -> str:
    source_def = get_condition_source_map().get(source_code)
    if not source_def:
        return "-"
    return _to_str(source_def.example) or "-"


def action_example_for_field(target_code: str) -> str:
    target_def = get_action_target_map().get(target_code)
    if not target_def:
        return "-"
    return _to_str(target_def.example) or "-"
