from decimal import Decimal

from django.test import TestCase

from customer.models import Address, Customer
from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition
from orders.models import Order
from orders.services.order_rule_resolver import OrderRuleResolverService


class OrderRuleResolverDynamicRulesTest(TestCase):
    def _create_order(
        self,
        *,
        api_id: str,
        payment_method: str = "Rechnung",
        shipping_method: str = "Standard",
        billing_country: str = "DE",
        shipping_country: str = "DE",
        total_price: Decimal = Decimal("0.00"),
        total_tax: Decimal = Decimal("0.00"),
        shipping_costs: Decimal = Decimal("0.00"),
    ) -> Order:
        customer = Customer.objects.create(
            erp_nr=f"ERP-{api_id}",
            name="Testkunde",
            is_gross=True,
        )
        billing_address = Address.objects.create(
            customer=customer,
            first_name="Max",
            last_name="Mustermann",
            country_code=billing_country,
            is_invoice=True,
        )
        shipping_address = Address.objects.create(
            customer=customer,
            first_name="Max",
            last_name="Mustermann",
            country_code=shipping_country,
            is_shipping=True,
        )
        return Order.objects.create(
            api_id=api_id,
            order_number=f"ORDER-{api_id}",
            customer=customer,
            billing_address=billing_address,
            shipping_address=shipping_address,
            payment_method=payment_method,
            shipping_method=shipping_method,
            total_price=total_price,
            total_tax=total_tax,
            shipping_costs=shipping_costs,
        )

    def test_single_source_condition_can_set_multiple_targets(self):
        order = self._create_order(
            api_id="A1",
            total_price=Decimal("150.00"),
        )
        rule = MicrotechOrderRule.objects.create(
            name="Grossbestellung",
            priority=1,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            source_field=MicrotechOrderRuleCondition.SourceField.ORDER_TOTAL,
            operator=MicrotechOrderRuleCondition.Operator.GREATER_THAN,
            expected_value="100",
            priority=1,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            target_field=MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID,
            target_value="77",
            priority=1,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            target_field=MicrotechOrderRuleAction.TargetField.VERSANDART_ID,
            target_value="88",
            priority=2,
        )

        resolved = OrderRuleResolverService().resolve_for_order(order=order)

        self.assertEqual(resolved.zahlungsart_id, 77)
        self.assertEqual(resolved.versandart_id, 88)

    def test_multiple_source_conditions_with_or_can_set_multiple_targets(self):
        order = self._create_order(
            api_id="A2",
            payment_method="Vorkasse",
            shipping_country="AT",
        )
        rule = MicrotechOrderRule.objects.create(
            name="AT oder PayPal",
            priority=1,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ANY,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            source_field=MicrotechOrderRuleCondition.SourceField.PAYMENT_METHOD,
            operator=MicrotechOrderRuleCondition.Operator.CONTAINS,
            expected_value="paypal",
            priority=1,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            source_field=MicrotechOrderRuleCondition.SourceField.SHIPPING_COUNTRY_CODE,
            operator=MicrotechOrderRuleCondition.Operator.EQUALS,
            expected_value="AT",
            priority=2,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            target_field=MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID,
            target_value="22",
            priority=1,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            target_field=MicrotechOrderRuleAction.TargetField.ZAHLUNGSBEDINGUNG,
            target_value="Sofort ohne Abzug",
            priority=2,
        )

        resolved = OrderRuleResolverService().resolve_for_order(order=order)

        self.assertEqual(resolved.zahlungsart_id, 22)
        self.assertEqual(resolved.zahlungsbedingung, "Sofort ohne Abzug")

    def test_dynamic_and_condition_must_match_all_or_fallback_to_next_rule(self):
        order = self._create_order(
            api_id="A3",
            payment_method="Rechnung",
            shipping_country="DE",
        )
        strict_rule = MicrotechOrderRule.objects.create(
            name="PayPal und DE",
            priority=1,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=strict_rule,
            source_field=MicrotechOrderRuleCondition.SourceField.PAYMENT_METHOD,
            operator=MicrotechOrderRuleCondition.Operator.CONTAINS,
            expected_value="paypal",
            priority=1,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=strict_rule,
            source_field=MicrotechOrderRuleCondition.SourceField.SHIPPING_COUNTRY_CODE,
            operator=MicrotechOrderRuleCondition.Operator.EQUALS,
            expected_value="DE",
            priority=2,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=strict_rule,
            target_field=MicrotechOrderRuleAction.TargetField.ZAHLUNGSART_ID,
            target_value="91",
            priority=1,
        )

        fallback_rule = MicrotechOrderRule.objects.create(
            name="Fallback Legacy",
            priority=2,
            is_active=True,
            customer_type=MicrotechOrderRule.CustomerType.ANY,
            zahlungsart_id=55,
        )
        self.assertIsNotNone(fallback_rule.pk)

        resolved = OrderRuleResolverService().resolve_for_order(order=order)

        self.assertEqual(resolved.zahlungsart_id, 55)
