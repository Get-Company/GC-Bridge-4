from __future__ import annotations

from dataclasses import dataclass

from django.db import OperationalError, ProgrammingError

from microtech.models import (
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleActionTarget,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionSource,
    MicrotechOrderRuleOperator,
)


@dataclass(frozen=True, slots=True)
class OperatorDef:
    code: str
    name: str
    engine_operator: str
    hint: str = ""


@dataclass(frozen=True, slots=True)
class ConditionSourceDef:
    code: str
    name: str
    engine_source_field: str
    value_type: str
    allowed_operator_codes: tuple[str, ...]
    hint: str = ""
    example: str = ""


@dataclass(frozen=True, slots=True)
class ActionTargetDef:
    code: str
    name: str
    engine_target_field: str
    value_type: str
    enum_values: tuple[str, ...]
    hint: str = ""
    example: str = ""


DEFAULT_OPERATOR_DEFS: tuple[OperatorDef, ...] = (
    OperatorDef(code="eq", name="==", engine_operator="eq"),
    OperatorDef(code="contains", name="enthaelt", engine_operator="contains"),
    OperatorDef(code="gt", name=">", engine_operator="gt"),
    OperatorDef(code="lt", name="<", engine_operator="lt"),
)

DEFAULT_CONDITION_SOURCE_DEFS: tuple[ConditionSourceDef, ...] = (
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.CUSTOMER_TYPE,
        name="Kundentyp",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.CUSTOMER_TYPE,
        value_type=MicrotechOrderRuleCondition.ValueType.ENUM,
        allowed_operator_codes=("eq",),
        hint="private/company/any",
        example="private",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.BILLING_COUNTRY_CODE,
        name="Rechnungsland (ISO2)",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.BILLING_COUNTRY_CODE,
        value_type=MicrotechOrderRuleCondition.ValueType.COUNTRY_CODE,
        allowed_operator_codes=("eq", "contains"),
        hint="ISO2, z. B. DE/AT/CH",
        example="DE",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.SHIPPING_COUNTRY_CODE,
        name="Lieferland (ISO2)",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.SHIPPING_COUNTRY_CODE,
        value_type=MicrotechOrderRuleCondition.ValueType.COUNTRY_CODE,
        allowed_operator_codes=("eq", "contains"),
        hint="ISO2, z. B. DE/AT/CH",
        example="AT",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.PAYMENT_METHOD,
        name="Zahlungsart",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.PAYMENT_METHOD,
        value_type=MicrotechOrderRuleCondition.ValueType.STRING,
        allowed_operator_codes=("eq", "contains"),
        hint="String",
        example="paypal",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.SHIPPING_METHOD,
        name="Versandart",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.SHIPPING_METHOD,
        value_type=MicrotechOrderRuleCondition.ValueType.STRING,
        allowed_operator_codes=("eq", "contains"),
        hint="String",
        example="dhl",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL,
        name="Bestellwert gesamt",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL,
        value_type=MicrotechOrderRuleCondition.ValueType.DECIMAL,
        allowed_operator_codes=("eq", "gt", "lt"),
        hint="Dezimalzahl",
        example="100.50",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL_TAX,
        name="Steuer gesamt",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL_TAX,
        value_type=MicrotechOrderRuleCondition.ValueType.DECIMAL,
        allowed_operator_codes=("eq", "gt", "lt"),
        hint="Dezimalzahl",
        example="19.00",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.SHIPPING_COSTS,
        name="Versandkosten",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.SHIPPING_COSTS,
        value_type=MicrotechOrderRuleCondition.ValueType.DECIMAL,
        allowed_operator_codes=("eq", "gt", "lt"),
        hint="Dezimalzahl",
        example="4.90",
    ),
    ConditionSourceDef(
        code=MicrotechOrderRuleCondition.SourceField.ORDER_NUMBER,
        name="Bestellnummer",
        engine_source_field=MicrotechOrderRuleCondition.SourceField.ORDER_NUMBER,
        value_type=MicrotechOrderRuleCondition.ValueType.STRING,
        allowed_operator_codes=("eq", "contains"),
        hint="String",
        example="SW100045",
    ),
)

DEFAULT_ACTION_TARGET_DEFS: tuple[ActionTargetDef, ...] = (
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.NA1_MODE,
        name="Na1 Modus",
        engine_target_field=MicrotechOrderRuleAction.TargetField.NA1_MODE,
        value_type=MicrotechOrderRuleAction.ValueType.ENUM,
        enum_values=tuple(MicrotechOrderRule.Na1Mode.values),
        hint="Empfaengertext-Steuerung",
        example="auto",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.NA1_STATIC_VALUE,
        name="Na1 statischer Text",
        engine_target_field=MicrotechOrderRuleAction.TargetField.NA1_STATIC_VALUE,
        value_type=MicrotechOrderRuleAction.ValueType.STRING,
        enum_values=(),
        example="Firma",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.VORGANGSART_ID,
        name="Vorgangsart-ID",
        engine_target_field=MicrotechOrderRuleAction.TargetField.VORGANGSART_ID,
        value_type=MicrotechOrderRuleAction.ValueType.INT,
        enum_values=(),
        example="111",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID,
        name="Zahlungsart-ID",
        engine_target_field=MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID,
        value_type=MicrotechOrderRuleAction.ValueType.INT,
        enum_values=(),
        example="22",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.VERSANDART_ID,
        name="Versandart-ID",
        engine_target_field=MicrotechOrderRuleAction.TargetField.VERSANDART_ID,
        value_type=MicrotechOrderRuleAction.ValueType.INT,
        enum_values=(),
        example="10",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.ZAHLUNGSBEDINGUNG,
        name="Zahlungsbedingung",
        engine_target_field=MicrotechOrderRuleAction.TargetField.ZAHLUNGSBEDINGUNG,
        value_type=MicrotechOrderRuleAction.ValueType.STRING,
        enum_values=(),
        example="Sofort ohne Abzug",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.ADD_PAYMENT_POSITION,
        name="Zusatzposition Zahlungsart anlegen",
        engine_target_field=MicrotechOrderRuleAction.TargetField.ADD_PAYMENT_POSITION,
        value_type=MicrotechOrderRuleAction.ValueType.BOOL,
        enum_values=(),
        example="true",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_ERP_NR,
        name="Zahlungs-Zusatzposition ERP-Nr",
        engine_target_field=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_ERP_NR,
        value_type=MicrotechOrderRuleAction.ValueType.STRING,
        enum_values=(),
        example="P",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_NAME,
        name="Zahlungs-Zusatzposition Name",
        engine_target_field=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_NAME,
        value_type=MicrotechOrderRuleAction.ValueType.STRING,
        enum_values=(),
        example="PayPal",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_MODE,
        name="Zahlungs-Zusatzposition Modus",
        engine_target_field=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_MODE,
        value_type=MicrotechOrderRuleAction.ValueType.ENUM,
        enum_values=tuple(MicrotechOrderRule.PaymentPositionMode.values),
        example="fixed",
    ),
    ActionTargetDef(
        code=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_VALUE,
        name="Zahlungs-Zusatzposition Wert",
        engine_target_field=MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_VALUE,
        value_type=MicrotechOrderRuleAction.ValueType.DECIMAL,
        enum_values=(),
        example="2.50",
    ),
)


def _db_has_rule_builder_tables() -> bool:
    try:
        MicrotechOrderRuleOperator.objects.exists()
        MicrotechOrderRuleConditionSource.objects.exists()
        MicrotechOrderRuleActionTarget.objects.exists()
        return True
    except (OperationalError, ProgrammingError):
        return False


def get_operator_defs() -> list[OperatorDef]:
    if not _db_has_rule_builder_tables():
        return list(DEFAULT_OPERATOR_DEFS)
    rows = list(
        MicrotechOrderRuleOperator.objects
        .filter(is_active=True)
        .order_by("priority", "id")
    )
    if not rows:
        return list(DEFAULT_OPERATOR_DEFS)
    return [
        OperatorDef(
            code=str(row.code).strip(),
            name=str(row.name).strip(),
            engine_operator=str(row.engine_operator).strip(),
            hint=str(row.hint or "").strip(),
        )
        for row in rows
        if str(row.code).strip()
    ]


def get_condition_source_defs() -> list[ConditionSourceDef]:
    if not _db_has_rule_builder_tables():
        return list(DEFAULT_CONDITION_SOURCE_DEFS)
    rows = list(
        MicrotechOrderRuleConditionSource.objects
        .filter(is_active=True)
        .prefetch_related("operators")
        .order_by("priority", "id")
    )
    if not rows:
        return list(DEFAULT_CONDITION_SOURCE_DEFS)
    defs: list[ConditionSourceDef] = []
    all_operator_codes = tuple(item.code for item in get_operator_defs())
    for row in rows:
        code = str(row.code).strip()
        if not code:
            continue
        allowed_codes = tuple(
            str(op.code).strip()
            for op in row.operators.filter(is_active=True).order_by("priority", "id")
            if str(op.code).strip()
        )
        defs.append(
            ConditionSourceDef(
                code=code,
                name=str(row.name).strip() or code,
                engine_source_field=str(row.engine_source_field).strip(),
                value_type=str(row.value_type).strip(),
                allowed_operator_codes=allowed_codes or all_operator_codes,
                hint=str(row.hint or "").strip(),
                example=str(row.example or "").strip(),
            )
        )
    return defs or list(DEFAULT_CONDITION_SOURCE_DEFS)


def get_action_target_defs() -> list[ActionTargetDef]:
    if not _db_has_rule_builder_tables():
        return list(DEFAULT_ACTION_TARGET_DEFS)
    rows = list(
        MicrotechOrderRuleActionTarget.objects
        .filter(is_active=True)
        .order_by("priority", "id")
    )
    if not rows:
        return list(DEFAULT_ACTION_TARGET_DEFS)
    defs: list[ActionTargetDef] = []
    for row in rows:
        code = str(row.code).strip()
        if not code:
            continue
        enum_values = tuple(
            item.strip()
            for item in str(row.enum_values or "").split(",")
            if item.strip()
        )
        defs.append(
            ActionTargetDef(
                code=code,
                name=str(row.name).strip() or code,
                engine_target_field=str(row.engine_target_field).strip(),
                value_type=str(row.value_type).strip(),
                enum_values=enum_values,
                hint=str(row.hint or "").strip(),
                example=str(row.example or "").strip(),
            )
        )
    return defs or list(DEFAULT_ACTION_TARGET_DEFS)


def get_operator_engine_map() -> dict[str, str]:
    return {item.code: item.engine_operator for item in get_operator_defs()}


def get_condition_source_map() -> dict[str, ConditionSourceDef]:
    return {item.code: item for item in get_condition_source_defs()}


def get_action_target_map() -> dict[str, ActionTargetDef]:
    return {item.code: item for item in get_action_target_defs()}
