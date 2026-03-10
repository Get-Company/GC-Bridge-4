from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from loguru import logger

from core.services import BaseService
from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition
from microtech.rule_builder import get_django_field_map, get_operator_engine_map, resolve_django_field_value
from orders.models import Order


_SALUTATION_VALUES = {
    "frau",
    "herr",
    "mr",
    "mrs",
    "ms",
    "miss",
    "madam",
    "madame",
    "monsieur",
    "weiblich",
    "male",
    "female",
}

_BOOL_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off", "nein"}


def _to_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_decimal(value: object) -> Decimal | None:
    text = _to_str(value)
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _to_str(value).lower()
    if text in _BOOL_TRUE_VALUES:
        return True
    if text in _BOOL_FALSE_VALUES:
        return False
    return None


def _to_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _to_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _to_str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ResolvedDatasetAction:
    action_type: str
    dataset_source_identifier: str = ""
    dataset_name: str = ""
    dataset_field_name: str = ""
    dataset_field_type: str = ""
    target_value: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedOrderRule:
    rule_id: int | None = None
    rule_name: str = ""
    customer_type: str = MicrotechOrderRule.CustomerType.PRIVATE
    na1_mode: str = MicrotechOrderRule.Na1Mode.AUTO
    na1_static_value: str = ""
    vorgangsart_id: int | None = None
    zahlungsart_id: int | None = None
    versandart_id: int | None = None
    zahlungsbedingung: str = ""
    add_payment_position: bool = False
    payment_position_erp_nr: str = ""
    payment_position_name: str = ""
    payment_position_mode: str = MicrotechOrderRule.PaymentPositionMode.FIXED
    payment_position_value: Decimal | None = None
    dataset_actions: tuple[ResolvedDatasetAction, ...] = ()

    @classmethod
    def from_rule(cls, *, rule: MicrotechOrderRule, customer_type: str) -> "ResolvedOrderRule":
        return cls(
            rule_id=rule.pk,
            rule_name=_to_str(rule.name),
            customer_type=customer_type,
        )


class OrderRuleResolverService(BaseService):
    model = MicrotechOrderRule

    def resolve_for_order(self, *, order: Order) -> ResolvedOrderRule:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        customer_type = self._detect_customer_type(order=order)
        order_label = _to_str(order.order_number) or f"id={order.pk}"

        rules = list(
            self.get_queryset()
            .filter(is_active=True)
            .prefetch_related("conditions", "actions", "actions__dataset", "actions__dataset_field")
            .order_by("priority", "id")
        )
        django_field_map = get_django_field_map()
        operator_engine_map = get_operator_engine_map()
        logger.info("Order {}: evaluating {} active rule(s).", order_label, len(rules))

        for rule in rules:
            if not self._matches_rule(
                rule=rule,
                order=order,
                order_label=order_label,
                django_field_map=django_field_map,
                operator_engine_map=operator_engine_map,
            ):
                logger.info(
                    "Order {}: rule {} ('{}') did not match.",
                    order_label,
                    rule.pk,
                    _to_str(rule.name),
                )
                continue

            resolved = ResolvedOrderRule.from_rule(rule=rule, customer_type=customer_type)
            resolved = replace(
                resolved,
                dataset_actions=self._collect_dataset_actions(rule=rule, order_label=order_label),
            )
            logger.info(
                "Order {}: rule {} ('{}') matched with {} dataset action(s).",
                order_label,
                rule.pk,
                _to_str(rule.name),
                len(resolved.dataset_actions),
            )
            return resolved

        logger.info("Order {}: no active rule matched, using defaults.", order_label)
        return ResolvedOrderRule(customer_type=customer_type)

    def _matches_rule(
        self,
        *,
        rule: MicrotechOrderRule,
        order: Order,
        order_label: str,
        django_field_map: dict[str, object],
        operator_engine_map: dict[str, str],
    ) -> bool:
        active_conditions = [condition for condition in rule.conditions.all() if condition.is_active]
        if not active_conditions:
            logger.info(
                "Order {}: rule {} ('{}') has no active conditions and acts as global fallback.",
                order_label,
                rule.pk,
                _to_str(rule.name),
            )
            return True

        evaluations: list[bool] = []
        for condition in sorted(active_conditions, key=lambda item: (item.priority, item.id)):
            field_path = _to_str(condition.django_field_path)
            field_def = django_field_map.get(field_path)
            operator_code = _to_str(condition.operator_code)

            if not field_def:
                logger.warning(
                    "Order {}: condition {} uses unknown django field path '{}'.",
                    order_label,
                    condition.pk,
                    field_path,
                )
                evaluations.append(False)
                continue

            allowed_operators = set(getattr(field_def, "allowed_operator_codes", ()) or ())
            if operator_code not in allowed_operators:
                logger.warning(
                    "Order {}: condition {} uses disallowed operator '{}' for field '{}'.",
                    order_label,
                    condition.pk,
                    operator_code,
                    field_path,
                )
                evaluations.append(False)
                continue

            engine_operator = _to_str(operator_engine_map.get(operator_code)) or operator_code
            actual_value = resolve_django_field_value(order=order, path=field_path)
            expected_raw = _to_str(condition.expected_value)
            value_kind = _to_str(getattr(field_def, "value_kind", "string")) or "string"

            result = self._evaluate_condition(
                operator=engine_operator,
                actual_value=actual_value,
                expected_raw=expected_raw,
                value_kind=value_kind,
            )
            evaluations.append(result)

            logger.info(
                "Order {}: rule {} ('{}') condition {} -> field='{}' operator='{}' expected='{}' actual='{}' => {}",
                order_label,
                rule.pk,
                _to_str(rule.name),
                condition.pk,
                field_path,
                operator_code,
                expected_raw,
                _to_str(actual_value),
                "MATCH" if result else "NO_MATCH",
            )

        if rule.condition_logic == MicrotechOrderRule.ConditionLogic.ANY:
            final_result = any(evaluations)
        else:
            final_result = all(evaluations)

        logger.info(
            "Order {}: rule {} ('{}') final condition result={} (logic='{}').",
            order_label,
            rule.pk,
            _to_str(rule.name),
            final_result,
            rule.condition_logic,
        )
        return final_result

    @classmethod
    def _evaluate_condition(
        cls,
        *,
        operator: str,
        actual_value: object,
        expected_raw: str,
        value_kind: str,
    ) -> bool:
        if operator == "is_empty":
            return actual_value is None or _to_str(actual_value) == ""

        if operator == "is_not_empty":
            return actual_value is not None and _to_str(actual_value) != ""

        if operator == MicrotechOrderRuleCondition.Operator.CONTAINS:
            if not expected_raw:
                return True
            return expected_raw.lower() in _to_str(actual_value).lower()

        if value_kind in {"int", "decimal"}:
            actual_decimal = _to_decimal(actual_value)
            expected_decimal = _to_decimal(expected_raw)
            if actual_decimal is None or expected_decimal is None:
                return False
            if operator == MicrotechOrderRuleCondition.Operator.GREATER_THAN:
                return actual_decimal > expected_decimal
            if operator == MicrotechOrderRuleCondition.Operator.LESS_THAN:
                return actual_decimal < expected_decimal
            return actual_decimal == expected_decimal

        if value_kind == "bool":
            actual_bool = _to_bool(actual_value)
            expected_bool = _to_bool(expected_raw)
            if actual_bool is None or expected_bool is None:
                return False
            return actual_bool == expected_bool

        if value_kind == "date":
            actual_date = _to_date(actual_value)
            expected_date = _to_date(expected_raw)
            if actual_date is None or expected_date is None:
                return False
            if operator == MicrotechOrderRuleCondition.Operator.GREATER_THAN:
                return actual_date > expected_date
            if operator == MicrotechOrderRuleCondition.Operator.LESS_THAN:
                return actual_date < expected_date
            return actual_date == expected_date

        if value_kind == "datetime":
            actual_dt = _to_datetime(actual_value)
            expected_dt = _to_datetime(expected_raw)
            if actual_dt is None or expected_dt is None:
                return False
            if operator == MicrotechOrderRuleCondition.Operator.GREATER_THAN:
                return actual_dt > expected_dt
            if operator == MicrotechOrderRuleCondition.Operator.LESS_THAN:
                return actual_dt < expected_dt
            return actual_dt == expected_dt

        # string
        if operator == MicrotechOrderRuleCondition.Operator.GREATER_THAN:
            return _to_str(actual_value).lower() > expected_raw.lower()
        if operator == MicrotechOrderRuleCondition.Operator.LESS_THAN:
            return _to_str(actual_value).lower() < expected_raw.lower()
        return _to_str(actual_value).lower() == expected_raw.lower()

    @classmethod
    def _collect_dataset_actions(
        cls,
        *,
        rule: MicrotechOrderRule,
        order_label: str,
    ) -> tuple[ResolvedDatasetAction, ...]:
        resolved: list[ResolvedDatasetAction] = []
        active_actions = [action for action in rule.actions.all() if action.is_active]

        for action in sorted(active_actions, key=lambda item: (item.priority, item.id)):
            action_type = _to_str(action.action_type)

            if action_type == MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION:
                erp_nr = _to_str(action.target_value)
                if not erp_nr:
                    logger.warning(
                        "Order {}: rule {} action {} ignored (missing ERP-Nr for create_extra_position).",
                        order_label,
                        rule.pk,
                        action.pk,
                    )
                    continue
                resolved.append(
                    ResolvedDatasetAction(
                        action_type=action_type,
                        target_value=erp_nr,
                    )
                )
                continue

            if action_type != MicrotechOrderRuleAction.ActionType.SET_FIELD:
                logger.warning(
                    "Order {}: rule {} action {} ignored (unknown action_type='{}').",
                    order_label,
                    rule.pk,
                    action.pk,
                    action_type,
                )
                continue

            if not action.dataset_id or not action.dataset_field_id:
                logger.warning(
                    "Order {}: rule {} action {} ignored (dataset/dataset_field missing).",
                    order_label,
                    rule.pk,
                    action.pk,
                )
                continue
            if action.dataset_field.dataset_id != action.dataset_id:
                logger.warning(
                    "Order {}: rule {} action {} ignored (dataset_field does not belong to dataset).",
                    order_label,
                    rule.pk,
                    action.pk,
                )
                continue

            resolved.append(
                ResolvedDatasetAction(
                    action_type=action_type,
                    dataset_source_identifier=_to_str(action.dataset.source_identifier),
                    dataset_name=_to_str(action.dataset.name),
                    dataset_field_name=_to_str(action.dataset_field.field_name),
                    dataset_field_type=_to_str(action.dataset_field.field_type),
                    target_value=_to_str(action.target_value),
                )
            )

        return tuple(resolved)

    @staticmethod
    def _country_code(value: str) -> str:
        return _to_str(value).upper()

    @classmethod
    def _detect_customer_type(cls, *, order: Order) -> str:
        addresses = [order.billing_address, order.shipping_address]
        for address in addresses:
            if address and cls._address_looks_like_company(address):
                return MicrotechOrderRule.CustomerType.COMPANY
        return MicrotechOrderRule.CustomerType.PRIVATE

    @classmethod
    def _address_looks_like_company(cls, address) -> bool:
        name1 = _to_str(getattr(address, "name1", ""))
        name2 = _to_str(getattr(address, "name2", ""))
        first_name = _to_str(getattr(address, "first_name", ""))
        last_name = _to_str(getattr(address, "last_name", ""))
        lowered = name1.lower()

        if not name1:
            return False
        if lowered in _SALUTATION_VALUES:
            return False
        if name2 and name1 == name2:
            return True
        if first_name or last_name:
            return False
        return True


__all__ = ["OrderRuleResolverService", "ResolvedDatasetAction", "ResolvedOrderRule"]
