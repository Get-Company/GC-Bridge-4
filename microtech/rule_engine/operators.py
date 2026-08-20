from __future__ import annotations

from orders.services.order_rule_resolver import (
    OrderRuleResolverService, _to_bool, _to_date, _to_datetime, _to_decimal, _to_str,
)


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
        return OrderRuleResolverService._evaluate_condition(
            operator="lt", actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
    if operator == "after":
        return OrderRuleResolverService._evaluate_condition(
            operator="gt", actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
    if operator == "is_true":
        return _to_bool(actual_value) is True
    if operator == "is_false":
        return _to_bool(actual_value) is False
    return OrderRuleResolverService._evaluate_condition(
        operator=operator, actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
