from __future__ import annotations

from microtech.rule_comparisons import (
    evaluate_comparison,
    to_bool as _to_bool,
    to_date as _to_date,
    to_datetime as _to_datetime,
    to_decimal as _to_decimal,
    to_str as _to_str,
)


def parse_list(raw) -> list[str]:
    """Split a rule value into list items on commas and newlines, trimmed, no blanks."""
    text = _to_str(raw)
    if not text:
        return []
    items = []
    for chunk in text.replace("\r", "\n").replace(",", "\n").split("\n"):
        item = chunk.strip()
        if item:
            items.append(item)
    return items


def _in_list(actual, expected) -> bool:
    needle = _to_str(actual).casefold()
    if not needle:
        return False
    return needle in {item.casefold() for item in parse_list(expected)}


def _between(actual, lo, hi, value_kind) -> bool:
    if value_kind in {"int", "decimal"}:
        a, l, h = _to_decimal(actual), _to_decimal(lo), _to_decimal(hi)
    elif value_kind == "date":
        a, l, h = _to_date(actual), _to_date(lo), _to_date(hi)
    elif value_kind == "datetime":
        a, l, h = _to_datetime(actual), _to_datetime(lo), _to_datetime(hi)
    else:
        a, l, h = _to_str(actual).lower(), _to_str(lo).lower(), _to_str(hi).lower()
    if a is None or l is None or h is None:
        return False
    return l <= a <= h


def evaluate_operator(operator, actual_value, expected_raw, expected_raw_2, value_kind) -> bool:
    if operator == "between":
        return _between(actual_value, expected_raw, expected_raw_2, value_kind)
    if operator == "before":
        return evaluate_comparison(
            operator="lt", actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
    if operator == "after":
        return evaluate_comparison(
            operator="gt", actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
    if operator == "is_true":
        return _to_bool(actual_value) is True
    if operator == "is_false":
        return _to_bool(actual_value) is False
    if operator == "in_list":
        return _in_list(actual_value, expected_raw)
    if operator == "not_in_list":
        return not _in_list(actual_value, expected_raw)
    return evaluate_comparison(
        operator=operator, actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
