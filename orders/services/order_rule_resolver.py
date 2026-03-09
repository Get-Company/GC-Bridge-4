from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from loguru import logger

from core.services import BaseService
from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition
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


def _to_int(value: object) -> int | None:
    text = _to_str(value)
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _to_bool(value: object) -> bool | None:
    text = _to_str(value).lower()
    if text in {"1", "true", "yes", "on", "ja"}:
        return True
    if text in {"0", "false", "no", "off", "nein"}:
        return False
    return None


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
        billing_country = self._country_code(
            _to_str(getattr(order.billing_address, "country_code", ""))
        )
        shipping_country = self._country_code(
            _to_str(getattr(order.shipping_address, "country_code", ""))
        )
        payment_method = _to_str(order.payment_method).lower()
        shipping_method = _to_str(order.shipping_method).lower()
        context = {
            MicrotechOrderRuleCondition.SourceField.CUSTOMER_TYPE: customer_type,
            MicrotechOrderRuleCondition.SourceField.BILLING_COUNTRY_CODE: billing_country,
            MicrotechOrderRuleCondition.SourceField.SHIPPING_COUNTRY_CODE: shipping_country,
            MicrotechOrderRuleCondition.SourceField.PAYMENT_METHOD: payment_method,
            MicrotechOrderRuleCondition.SourceField.SHIPPING_METHOD: shipping_method,
            MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL: order.total_price,
            MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL_TAX: order.total_tax,
            MicrotechOrderRuleCondition.SourceField.SHIPPING_COSTS: order.shipping_costs,
            MicrotechOrderRuleCondition.SourceField.ORDER_NUMBER: _to_str(order.order_number),
        }
        order_label = _to_str(order.order_number) or f"id={order.pk}"
        logger.info(
            "Resolving Microtech order rule for order {} (payment_method='{}', shipping_method='{}').",
            order_label,
            _to_str(order.payment_method),
            _to_str(order.shipping_method),
        )

        rules = list(
            self.get_queryset()
            .filter(is_active=True)
            .prefetch_related("conditions", "actions")
            .order_by("priority", "id")
        )
        logger.info("Order {}: evaluating {} active rule(s).", order_label, len(rules))

        for rule in rules:
            if not self._matches_rule(rule=rule, context=context, order_label=order_label):
                logger.info(
                    "Order {}: rule {} ('{}') did not match.",
                    order_label,
                    rule.pk,
                    _to_str(rule.name),
                )
                continue
            resolved = ResolvedOrderRule.from_rule(rule=rule, customer_type=customer_type)
            logger.info(
                "Order {}: rule {} ('{}') matched. Applying actions.",
                order_label,
                rule.pk,
                _to_str(rule.name),
            )
            resolved = self._apply_dynamic_actions(rule=rule, resolved=resolved)
            logger.info(
                "Order {}: resolved rule result -> rule_id={}, zahlungsart_id={}, versandart_id={}, "
                "vorgangsart_id={}, add_payment_position={}, payment_position_erp_nr='{}', "
                "payment_position_mode='{}', payment_position_value='{}'.",
                order_label,
                resolved.rule_id,
                resolved.zahlungsart_id,
                resolved.versandart_id,
                resolved.vorgangsart_id,
                resolved.add_payment_position,
                _to_str(resolved.payment_position_erp_nr),
                resolved.payment_position_mode,
                _to_str(resolved.payment_position_value),
            )
            return resolved

        logger.info("Order {}: no active rule matched, using defaults.", order_label)
        return ResolvedOrderRule(customer_type=customer_type)

    def _matches_rule(
        self,
        *,
        rule: MicrotechOrderRule,
        context: dict[str, object],
        order_label: str = "",
    ) -> bool:
        active_conditions = [condition for condition in rule.conditions.all() if condition.is_active]
        if not active_conditions:
            # Dynamic-only mode: a rule without conditions is a global fallback.
            logger.info(
                "Order {}: rule {} ('{}') has no active conditions and acts as global fallback.",
                order_label or "?",
                rule.pk,
                _to_str(rule.name),
            )
            return True
        return self._matches_dynamic_conditions(
            rule=rule,
            active_conditions=active_conditions,
            context=context,
            order_label=order_label,
        )

    def _matches_dynamic_conditions(
        self,
        *,
        rule: MicrotechOrderRule,
        active_conditions: list[MicrotechOrderRuleCondition],
        context: dict[str, object],
        order_label: str = "",
    ) -> bool:
        sorted_conditions = sorted(active_conditions, key=lambda item: (item.priority, item.id))
        evaluations: list[bool] = []
        for condition in sorted_conditions:
            result = self._evaluate_condition(condition=condition, context=context)
            evaluations.append(result)
            actual_value = context.get(condition.source_field)
            logger.info(
                "Order {}: rule {} ('{}') condition {} -> {} {} '{}' (actual='{}') => {}",
                order_label or "?",
                rule.pk,
                _to_str(rule.name),
                condition.pk,
                condition.source_field,
                condition.operator,
                _to_str(condition.expected_value),
                _to_str(actual_value),
                "MATCH" if result else "NO_MATCH",
            )
        if rule.condition_logic == MicrotechOrderRule.ConditionLogic.ANY:
            final_result = any(evaluations)
        else:
            final_result = all(evaluations)
        logger.info(
            "Order {}: rule {} ('{}') final condition result={} (logic='{}').",
            order_label or "?",
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
        condition: MicrotechOrderRuleCondition,
        context: dict[str, object],
    ) -> bool:
        actual_value = context.get(condition.source_field)
        expected_raw = _to_str(condition.expected_value)
        operator = condition.operator

        if operator == MicrotechOrderRuleCondition.Operator.CONTAINS:
            if not expected_raw:
                return True
            return expected_raw.lower() in _to_str(actual_value).lower()

        if operator in (
            MicrotechOrderRuleCondition.Operator.GREATER_THAN,
            MicrotechOrderRuleCondition.Operator.LESS_THAN,
        ):
            actual_decimal = _to_decimal(actual_value)
            expected_decimal = _to_decimal(expected_raw)
            if actual_decimal is None or expected_decimal is None:
                return False
            if operator == MicrotechOrderRuleCondition.Operator.GREATER_THAN:
                return actual_decimal > expected_decimal
            return actual_decimal < expected_decimal

        # equals
        numeric_fields = {
            MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL,
            MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL_TAX,
            MicrotechOrderRuleCondition.SourceField.SHIPPING_COSTS,
        }
        if condition.source_field in numeric_fields:
            actual_decimal = _to_decimal(actual_value)
            expected_decimal = _to_decimal(expected_raw)
            if actual_decimal is None or expected_decimal is None:
                return False
            return actual_decimal == expected_decimal
        return _to_str(actual_value).lower() == expected_raw.lower()

    @classmethod
    def _apply_dynamic_actions(
        cls,
        *,
        rule: MicrotechOrderRule,
        resolved: ResolvedOrderRule,
    ) -> ResolvedOrderRule:
        active_actions = [
            action
            for action in rule.actions.all()
            if action.is_active
        ]
        if not active_actions:
            logger.info(
                "Rule {} ('{}') matched but has no active actions.",
                rule.pk,
                _to_str(rule.name),
            )
            return resolved

        for action in sorted(active_actions, key=lambda item: (item.priority, item.id)):
            before = resolved
            resolved = cls._apply_action(action=action, resolved=resolved, rule_id=rule.pk)
            if resolved != before:
                logger.info(
                    "Rule {} ('{}') action {}='{}' applied.",
                    rule.pk,
                    _to_str(rule.name),
                    action.target_field,
                    _to_str(action.target_value),
                )
            else:
                logger.info(
                    "Rule {} ('{}') action {}='{}' was ignored.",
                    rule.pk,
                    _to_str(rule.name),
                    action.target_field,
                    _to_str(action.target_value),
                )
        return resolved

    @classmethod
    def _apply_action(
        cls,
        *,
        action: MicrotechOrderRuleAction,
        resolved: ResolvedOrderRule,
        rule_id: int | None,
    ) -> ResolvedOrderRule:
        target = action.target_field
        raw_value = _to_str(action.target_value)

        int_targets = {
            MicrotechOrderRuleAction.TargetField.VORGANGSART_ID,
            MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID,
            MicrotechOrderRuleAction.TargetField.VERSANDART_ID,
        }
        string_targets = {
            MicrotechOrderRuleAction.TargetField.NA1_STATIC_VALUE,
            MicrotechOrderRuleAction.TargetField.ZAHLUNGSBEDINGUNG,
            MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_ERP_NR,
            MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_NAME,
        }

        if target in int_targets:
            parsed = _to_int(raw_value)
            if parsed is None:
                logger.warning("Rule {} action {} ignored: invalid int value '{}'.", rule_id, target, raw_value)
                return resolved
            return replace(resolved, **{target: parsed})

        if target in string_targets:
            return replace(resolved, **{target: raw_value})

        if target == MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_VALUE:
            parsed_decimal = _to_decimal(raw_value)
            if parsed_decimal is None:
                logger.warning("Rule {} action {} ignored: invalid decimal value '{}'.", rule_id, target, raw_value)
                return resolved
            return replace(resolved, payment_position_value=parsed_decimal)

        if target == MicrotechOrderRuleAction.TargetField.ADD_PAYMENT_POSITION:
            parsed_bool = _to_bool(raw_value)
            if parsed_bool is None:
                logger.warning("Rule {} action {} ignored: invalid boolean value '{}'.", rule_id, target, raw_value)
                return resolved
            return replace(resolved, add_payment_position=parsed_bool)

        if target == MicrotechOrderRuleAction.TargetField.NA1_MODE:
            valid_values = set(MicrotechOrderRule.Na1Mode.values)
            if raw_value not in valid_values:
                logger.warning("Rule {} action {} ignored: unknown enum value '{}'.", rule_id, target, raw_value)
                return resolved
            return replace(resolved, na1_mode=raw_value)

        if target == MicrotechOrderRuleAction.TargetField.PAYMENT_POSITION_MODE:
            valid_values = set(MicrotechOrderRule.PaymentPositionMode.values)
            if raw_value not in valid_values:
                logger.warning("Rule {} action {} ignored: unknown enum value '{}'.", rule_id, target, raw_value)
                return resolved
            return replace(resolved, payment_position_mode=raw_value)

        logger.warning("Rule {} action ignored: unknown target field '{}'.", rule_id, target)
        return resolved

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


__all__ = ["OrderRuleResolverService", "ResolvedOrderRule"]
