from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.services import BaseService
from microtech.models import MicrotechOrderRule
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
            na1_mode=rule.na1_mode,
            na1_static_value=_to_str(rule.na1_static_value),
            vorgangsart_id=rule.vorgangsart_id,
            zahlungsart_id=rule.zahlungsart_id,
            versandart_id=rule.versandart_id,
            zahlungsbedingung=_to_str(rule.zahlungsbedingung),
            add_payment_position=bool(rule.add_payment_position),
            payment_position_erp_nr=_to_str(rule.payment_position_erp_nr),
            payment_position_name=_to_str(rule.payment_position_name),
            payment_position_mode=rule.payment_position_mode,
            payment_position_value=rule.payment_position_value,
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

        rules = (
            self.get_queryset()
            .filter(is_active=True)
            .order_by("priority", "id")
        )

        for rule in rules:
            if not self._matches_customer_type(rule=rule, customer_type=customer_type):
                continue
            if not self._matches_country(
                rule=rule,
                billing_country=billing_country,
                shipping_country=shipping_country,
            ):
                continue
            if not self._matches_contains(rule.payment_method_pattern, payment_method):
                continue
            if not self._matches_contains(rule.shipping_method_pattern, shipping_method):
                continue
            return ResolvedOrderRule.from_rule(rule=rule, customer_type=customer_type)

        return ResolvedOrderRule(customer_type=customer_type)

    @staticmethod
    def _matches_customer_type(*, rule: MicrotechOrderRule, customer_type: str) -> bool:
        if rule.customer_type == MicrotechOrderRule.CustomerType.ANY:
            return True
        return rule.customer_type == customer_type

    @classmethod
    def _matches_country(
        cls,
        *,
        rule: MicrotechOrderRule,
        billing_country: str,
        shipping_country: str,
    ) -> bool:
        rule_billing = cls._country_code(rule.billing_country_code)
        rule_shipping = cls._country_code(rule.shipping_country_code)
        has_billing = bool(rule_billing)
        has_shipping = bool(rule_shipping)

        if not has_billing and not has_shipping:
            return True

        billing_match = has_billing and billing_country == rule_billing
        shipping_match = has_shipping and shipping_country == rule_shipping

        if rule.country_match_mode == MicrotechOrderRule.CountryMatchMode.BILLING_ONLY:
            return billing_match if has_billing else True
        if rule.country_match_mode == MicrotechOrderRule.CountryMatchMode.SHIPPING_ONLY:
            return shipping_match if has_shipping else True
        if rule.country_match_mode == MicrotechOrderRule.CountryMatchMode.BOTH:
            if has_billing and not billing_match:
                return False
            if has_shipping and not shipping_match:
                return False
            return True

        # either
        if has_billing and has_shipping:
            return billing_match or shipping_match
        if has_billing:
            return billing_match
        if has_shipping:
            return shipping_match
        return True

    @staticmethod
    def _matches_contains(pattern: str, value: str) -> bool:
        pattern = _to_str(pattern).lower()
        if not pattern:
            return True
        return pattern in value

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
