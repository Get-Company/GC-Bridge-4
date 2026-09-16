"""Pure value conversion and comparison helpers for the rule engines.

Both the legacy order resolver and the trigger-based rule engine need the same
comparison semantics.  Keeping them here prevents the new engine from
depending on a private method of the legacy service.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


_BOOL_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off", "nein"}


def to_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_decimal(value: object) -> Decimal | None:
    text = to_str(value)
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = to_str(value).lower()
    if text in _BOOL_TRUE_VALUES:
        return True
    if text in _BOOL_FALSE_VALUES:
        return False
    return None


def to_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = to_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def to_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = to_str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def evaluate_comparison(
    *,
    operator: str,
    actual_value: object,
    expected_raw: str,
    value_kind: str,
) -> bool:
    """Evaluate one normalized comparison without database or model access."""
    if operator == "is_empty":
        return actual_value is None or to_str(actual_value) == ""

    if operator == "is_not_empty":
        return actual_value is not None and to_str(actual_value) != ""

    if operator == "ne":
        return not evaluate_comparison(
            operator="eq",
            actual_value=actual_value,
            expected_raw=expected_raw,
            value_kind=value_kind,
        )

    if operator == "contains":
        if not expected_raw:
            return True
        return expected_raw.lower() in to_str(actual_value).lower()

    if value_kind in {"int", "decimal"}:
        actual_decimal = to_decimal(actual_value)
        expected_decimal = to_decimal(expected_raw)
        if actual_decimal is None or expected_decimal is None:
            return False
        if operator == "gt":
            return actual_decimal > expected_decimal
        if operator == "lt":
            return actual_decimal < expected_decimal
        return actual_decimal == expected_decimal

    if value_kind == "bool":
        actual_bool = to_bool(actual_value)
        expected_bool = to_bool(expected_raw)
        if actual_bool is None or expected_bool is None:
            return False
        return actual_bool == expected_bool

    if value_kind == "date":
        actual_date = to_date(actual_value)
        expected_date = to_date(expected_raw)
        if actual_date is None or expected_date is None:
            return False
        if operator == "gt":
            return actual_date > expected_date
        if operator == "lt":
            return actual_date < expected_date
        return actual_date == expected_date

    if value_kind == "datetime":
        actual_dt = to_datetime(actual_value)
        expected_dt = to_datetime(expected_raw)
        if actual_dt is None or expected_dt is None:
            return False
        if operator == "gt":
            return actual_dt > expected_dt
        if operator == "lt":
            return actual_dt < expected_dt
        return actual_dt == expected_dt

    if operator == "gt":
        return to_str(actual_value).lower() > expected_raw.lower()
    if operator == "lt":
        return to_str(actual_value).lower() < expected_raw.lower()
    return to_str(actual_value).lower() == expected_raw.lower()
