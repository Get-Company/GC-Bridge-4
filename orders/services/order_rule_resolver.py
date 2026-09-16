from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from loguru import logger

from core.services import BaseService
from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_comparisons import (
    evaluate_comparison,
    to_str as _to_str,
)
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

def address_looks_like_company(address) -> bool:
    name1 = _to_str(getattr(address, "name1", ""))
    title = _to_str(getattr(address, "title", ""))
    lowered = name1.lower()

    if not name1:
        return False
    if title and name1.casefold() == title.casefold():
        return False
    if lowered in _SALUTATION_VALUES:
        return False
    return True


def detect_customer_type(*, order) -> str:
    for address in (order.billing_address, order.shipping_address):
        if address and address_looks_like_company(address):
            return MicrotechOrderRule.CustomerType.COMPANY
    return MicrotechOrderRule.CustomerType.PRIVATE


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
        return evaluate_comparison(
            operator=operator,
            actual_value=actual_value,
            expected_raw=expected_raw,
            value_kind=value_kind,
        )

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

            if action_type in {
                MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION,
                MicrotechOrderRuleAction.ActionType.CREATE_SHIPPING_POSITION,
            }:
                erp_nr = _to_str(action.target_value)
                if not erp_nr:
                    logger.warning(
                        "Order {}: rule {} action {} ignored (missing ERP-Nr for {}).",
                        order_label,
                        rule.pk,
                        action.pk,
                        action_type,
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
        return detect_customer_type(order=order)

    @classmethod
    def _address_looks_like_company(cls, address) -> bool:
        return address_looks_like_company(address)


__all__ = [
    "OrderRuleResolverService",
    "ResolvedDatasetAction",
    "ResolvedOrderRule",
    "detect_customer_type",
    "address_looks_like_company",
]
