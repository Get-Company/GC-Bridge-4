"""Apply the editable standard mapping rules to precomputed code values."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from microtech.graphql_schema import get_rule_action_input_types
from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.customer_resolver import CustomerRuleContext
from microtech.rule_engine.execution import RuleExecutionService

ORDER_MAPPING_TASK = "orders.microtech_order_mapping"
ORDER_POSITION_MAPPING_TASK = "orders.microtech_order_position_mapping"
CUSTOMER_MAPPING_TASK = "customer.microtech_customer_mapping"
PRODUCT_MAPPING_TASK = "products.microtech_product_mapping"


@dataclass(frozen=True, slots=True)
class OrderMappingContext:
    order: object
    code_values: dict

    def __getattr__(self, name: str):
        return getattr(self.order, name)


@dataclass(frozen=True)
class OrderPositionMappingContext:
    detail: object
    code_values: dict

    def __getattr__(self, name: str):
        return getattr(self.detail, name)

    @cached_property
    def product(self):
        from products.models import Product

        return Product.objects.filter(erp_nr=self.detail.erp_nr).prefetch_related(
            "prices__sales_channel"
        ).first()

    @cached_property
    def shopware_price_per_100(self):
        """Scale the ordered price for Microtech's percent unit; never reprice."""
        from orders.services.order_price import OrderPriceService

        return OrderPriceService().unit_price(self.detail) * 100

    @cached_property
    def bridge_price(self):
        """The channel's net product price, before the product factor is applied.

        Choosing this value is the editable position rule's responsibility.
        Never fall back to a different channel or to a rounded unit price.
        """
        channel_id = self.detail.order.sales_channel_id
        price = None
        if self.product:
            price = next(
                (
                    item for item in self.product.prices.all()
                    if item.sales_channel and item.sales_channel.sales_channel_id == channel_id
                ),
                None,
            )
        if price is None:
            raise ValueError(
                f"Kein Bridge-Preis für Artikel {self.detail.erp_nr} "
                f"im Verkaufskanal {channel_id}."
            )
        if price.is_special_active:
            return price.get_special_price()
        if (
            price.rebate_quantity
            and price.rebate_price is not None
            and self.detail.quantity >= price.rebate_quantity
        ):
            return price.get_rebate_price()
        return price.get_standard_price()


def _coerce_like_code_value(*, field_name: str, value: str, code_values: dict):
    code_value = code_values.get(field_name)
    if isinstance(code_value, bool):
        return str(value or "").strip().lower() in {"1", "true", "yes", "ja", "on"}
    if isinstance(code_value, int):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return value
    return value


def _resolve_mapping_fields(
    *,
    task_name: str,
    root_instance: object,
    code_values: dict,
    target_scope: str | None = None,
) -> dict:
    allowed_input_types = get_rule_action_input_types(task_name, target_scope or "")
    matches = RuleExecutionService().resolve_matching_rules(
        task_name=task_name,
        phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
        root_instance=root_instance,
        action_scope=target_scope,
    )
    resolved: dict = {}
    for match in matches:
        for action in match.actions:
            if (
                action.action_type != MicrotechOrderRuleAction.ActionType.SET_FIELD
                or not action.field_path
            ):
                continue
            if allowed_input_types and action.graphql_field.split(".", 1)[0] not in allowed_input_types:
                continue
            resolved[action.field_path] = _coerce_like_code_value(
                field_name=action.field_path,
                value=action.value,
                code_values=code_values,
            )
    return resolved


def resolve_order_mapping_fields(*, order, code_values: dict) -> dict:
    return _resolve_mapping_fields(
        task_name=ORDER_MAPPING_TASK,
        root_instance=OrderMappingContext(order=order, code_values=code_values),
        code_values=code_values,
        target_scope=MicrotechOrderRuleAction.TargetScope.ORDER,
    )


def resolve_order_position_mapping_fields(*, detail, code_values: dict) -> dict:
    return _resolve_mapping_fields(
        task_name=ORDER_POSITION_MAPPING_TASK,
        root_instance=OrderPositionMappingContext(detail=detail, code_values=code_values),
        code_values=code_values,
        target_scope=MicrotechOrderRuleAction.TargetScope.POSITION,
    )


def resolve_customer_mapping_fields(
    *,
    customer,
    shipping_address,
    billing_address,
    address,
    target_scope: str,
    code_values: dict,
) -> dict:
    return _resolve_mapping_fields(
        task_name=CUSTOMER_MAPPING_TASK,
        root_instance=CustomerRuleContext(
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            address=address,
            code_values=code_values,
        ),
        code_values=code_values,
        target_scope=target_scope,
    )


def resolve_product_mapping_fields(*, product, code_values: dict) -> dict:
    resolved = _resolve_mapping_fields(
        task_name=PRODUCT_MAPPING_TASK,
        root_instance=product,
        code_values=code_values,
        target_scope=MicrotechOrderRuleAction.TargetScope.PRODUCT,
    )
    return {"unit": resolved["unit"]} if "unit" in resolved else {}


__all__ = [
    "CUSTOMER_MAPPING_TASK",
    "ORDER_MAPPING_TASK",
    "ORDER_POSITION_MAPPING_TASK",
    "PRODUCT_MAPPING_TASK",
    "resolve_customer_mapping_fields",
    "resolve_order_mapping_fields",
    "resolve_order_position_mapping_fields",
    "resolve_product_mapping_fields",
]
