from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition


_CONDITION_FIELD_META: dict[str, dict[str, object]] = {
    MicrotechOrderRuleCondition.SourceField.CUSTOMER_TYPE: {
        "type": "enum",
        "allowed_operators": {MicrotechOrderRuleCondition.Operator.EQUALS},
        "example": "private | company | any",
    },
    MicrotechOrderRuleCondition.SourceField.BILLING_COUNTRY_CODE: {
        "type": "country_code",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.CONTAINS,
        },
        "example": "DE, AT, CH",
    },
    MicrotechOrderRuleCondition.SourceField.SHIPPING_COUNTRY_CODE: {
        "type": "country_code",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.CONTAINS,
        },
        "example": "DE, AT, CH",
    },
    MicrotechOrderRuleCondition.SourceField.PAYMENT_METHOD: {
        "type": "string",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.CONTAINS,
        },
        "example": "paypal, rechnung, vorkasse",
    },
    MicrotechOrderRuleCondition.SourceField.SHIPPING_METHOD: {
        "type": "string",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.CONTAINS,
        },
        "example": "dhl, spedition",
    },
    MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL: {
        "type": "decimal",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.GREATER_THAN,
            MicrotechOrderRuleCondition.Operator.LESS_THAN,
        },
        "example": "100 oder 100.50",
    },
    MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL_TAX: {
        "type": "decimal",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.GREATER_THAN,
            MicrotechOrderRuleCondition.Operator.LESS_THAN,
        },
        "example": "19 oder 19.00",
    },
    MicrotechOrderRuleCondition.SourceField.SHIPPING_COSTS: {
        "type": "decimal",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.GREATER_THAN,
            MicrotechOrderRuleCondition.Operator.LESS_THAN,
        },
        "example": "0 oder 4.90",
    },
    MicrotechOrderRuleCondition.SourceField.ORDER_NUMBER: {
        "type": "string",
        "allowed_operators": {
            MicrotechOrderRuleCondition.Operator.EQUALS,
            MicrotechOrderRuleCondition.Operator.CONTAINS,
        },
        "example": "SW100045",
    },
}

_ACTION_FIELD_META: dict[str, dict[str, object]] = {
    MicrotechOrderRuleAction.TargetField.NA1_MODE: {
        "type": "enum",
        "allowed_values": set(MicrotechOrderRule.Na1Mode.values),
        "example": "auto | firma_or_salutation | salutation_only | static",
    },
    MicrotechOrderRuleAction.TargetField.NA1_STATIC_VALUE: {
        "type": "string",
        "example": "Firma",
    },
    MicrotechOrderRuleAction.TargetField.VORGANGSART_ID: {
        "type": "int",
        "example": "111",
    },
    MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID: {
        "type": "int",
        "example": "22",
    },
    MicrotechOrderRuleAction.TargetField.VERSANDART_ID: {
        "type": "int",
        "example": "10",
    },
    MicrotechOrderRuleAction.TargetField.ZAHLUNGSBEDINGUNG: {
        "type": "string",
        "example": "Sofort ohne Abzug",
    },
    MicrotechOrderRuleAction.TargetField.ADD_PAYMENT_POSITION: {
        "type": "bool",
        "example": "true oder false",
    },
    MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_ERP_NR: {
        "type": "string",
        "example": "P",
    },
    MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_NAME: {
        "type": "string",
        "example": "PayPal",
    },
    MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_MODE: {
        "type": "enum",
        "allowed_values": set(MicrotechOrderRule.PaymentPositionMode.values),
        "example": "fixed | percent_total",
    },
    MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_VALUE: {
        "type": "decimal",
        "example": "2.50 oder 3.00 (bei percent_total = Prozentwert)",
    },
}

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


class MicrotechOrderRuleConditionForm(forms.ModelForm):
    class Meta:
        model = MicrotechOrderRuleCondition
        fields = ("is_active", "priority", "source_field", "operator", "expected_value")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expected_value"].help_text = (
            "Beispiele je Source-Feld: Kundentyp=private/company/any, Land=DE, Zahlungsart=paypal, "
            "Bestellwert=100.50."
        )

    def clean(self):
        cleaned_data = super().clean()
        source_field = _to_str(cleaned_data.get("source_field"))
        operator = _to_str(cleaned_data.get("operator"))
        expected_value = _to_str(cleaned_data.get("expected_value"))

        if not source_field or not operator:
            return cleaned_data

        meta = _CONDITION_FIELD_META.get(source_field, {})
        allowed_operators = set(meta.get("allowed_operators", set()))
        if allowed_operators and operator not in allowed_operators:
            allowed = ", ".join(sorted(allowed_operators))
            self.add_error(
                "operator",
                f"Operator '{operator}' ist fuer dieses Source-Feld nicht erlaubt. Erlaubt: {allowed}.",
            )
            return cleaned_data

        field_type = _to_str(meta.get("type"))
        if field_type == "decimal":
            parsed = _parse_decimal(expected_value)
            if parsed is None:
                self.add_error("expected_value", "Vergleichswert muss eine Dezimalzahl sein (z. B. 100.50).")
                return cleaned_data
            cleaned_data["expected_value"] = _normalize_decimal(parsed)
            return cleaned_data

        if field_type == "country_code":
            if not expected_value:
                self.add_error("expected_value", "Vergleichswert darf nicht leer sein (z. B. DE).")
                return cleaned_data
            cleaned_data["expected_value"] = expected_value.upper()
            return cleaned_data

        if source_field == MicrotechOrderRuleCondition.SourceField.CUSTOMER_TYPE:
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
        self.fields["target_value"].help_text = (
            "Typ je Target-Feld: IDs=Integer, add_payment_position=Bool, payment_position_value=Dezimalzahl, "
            "na1_mode/payment_position_mode=Enum."
        )

    def clean(self):
        cleaned_data = super().clean()
        target_field = _to_str(cleaned_data.get("target_field"))
        target_value = _to_str(cleaned_data.get("target_value"))
        if not target_field:
            return cleaned_data

        meta = _ACTION_FIELD_META.get(target_field, {})
        field_type = _to_str(meta.get("type"))

        if field_type == "int":
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

        if field_type == "decimal":
            parsed_decimal = _parse_decimal(target_value)
            if parsed_decimal is None:
                self.add_error("target_value", "Zielwert muss eine Dezimalzahl sein (z. B. 2.50).")
                return cleaned_data
            cleaned_data["target_value"] = _normalize_decimal(parsed_decimal)
            return cleaned_data

        if field_type == "bool":
            normalized = target_value.lower()
            if normalized in _BOOL_TRUE_VALUES:
                cleaned_data["target_value"] = "true"
                return cleaned_data
            if normalized in _BOOL_FALSE_VALUES:
                cleaned_data["target_value"] = "false"
                return cleaned_data
            self.add_error("target_value", "Erlaubte Bool-Werte: true/false, ja/nein, 1/0.")
            return cleaned_data

        if field_type == "enum":
            allowed_values = set(meta.get("allowed_values", set()))
            if target_value not in allowed_values:
                allowed = ", ".join(sorted(allowed_values))
                self.add_error("target_value", f"Ungueltiger Enum-Wert. Erlaubt: {allowed}.")
                return cleaned_data
            return cleaned_data

        cleaned_data["target_value"] = target_value
        return cleaned_data


def condition_example_for_field(source_field: str) -> str:
    meta = _CONDITION_FIELD_META.get(source_field, {})
    return _to_str(meta.get("example")) or "-"


def action_example_for_field(target_field: str) -> str:
    meta = _ACTION_FIELD_META.get(target_field, {})
    return _to_str(meta.get("example")) or "-"
