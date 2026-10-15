from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition, MicrotechOrderRuleConditionGroup, RuleTrigger
from microtech.rule_builder import get_order_detail_field_defs
from microtech.rule_engine.mapping_resolver import ORDER_POSITION_MAPPING_TASK
from orders.models import Order, OrderDetail
from orders.services.order_rule_resolver import ResolvedOrderRule
from orders.services.order_upsert_microtech import OrderUpsertMicrotechService
from products.models import Price, Product
from shopware.models import ShopwareSettings


class SwissPositionPriceRuleTest(TestCase):
    def setUp(self):
        self.channel = ShopwareSettings.objects.create(name="CH test", sales_channel_id="ch-test")
        self.order = Order.objects.create(api_id="price-rule-test", order_number="TEST-CH", sales_channel_id="ch-test")
        self.product = Product.objects.create(erp_nr="FACTOR-TEST", sku="factor-test", factor=100)
        self.price = Price.objects.create(product=self.product, sales_channel=self.channel,
                                          price=Decimal("153.40"), rebate_quantity=100, rebate_price=Decimal("144.80"))
        self.detail = OrderDetail.objects.create(order=self.order, erp_nr=self.product.erp_nr, quantity=100,
                                                unit_price=Decimal("1.45"), total_price=Decimal("144.80"))
        trigger, _ = RuleTrigger.objects.get_or_create(task_name=ORDER_POSITION_MAPPING_TASK,
                                                       defaults={"label": "Position", "context_root": "orders.OrderDetail"})
        rule = MicrotechOrderRule.objects.create(name="CH factor price", trigger=trigger, engine_enabled=True, shadow_mode=False)
        group = MicrotechOrderRuleConditionGroup.objects.create(rule=rule, logic="all")
        for field, value in (("order__sales_channel_id", "ch-test"), ("product__factor", "100")):
            MicrotechOrderRuleCondition.objects.create(rule=rule, group=group, django_field_path=field, operator_code="eq", expected_value=value)
        for field, value in (("price", "{{ bridge_price }}"), ("unit", "% Stck")):
            MicrotechOrderRuleAction.objects.create(rule=rule, graphql_field=f"VorgangPositionInput.{field}",
                                                    target_scope="position", target_value=value)

    def positions(self):
        with patch("orders.services.order_upsert_microtech.MicrotechArtikelService") as article:
            article.return_value.find.return_value = True
            article.return_value.get_unit.return_value = "% Stck"
            return OrderUpsertMicrotechService()._build_graphql_positions(
                order=self.order, resolved_rule=ResolvedOrderRule(rule_id=None, rule_name=""), client=MagicMock())[0]

    def test_tier_price_is_exported_without_dividing_or_rounding_the_unit_price(self):
        position = self.positions()[0]
        self.assertEqual(Decimal(position["price"].replace(",", ".")), Decimal("144.80"))
        self.assertEqual(position["unit"], "% Stck")

    def test_below_tier_uses_standard_bridge_price(self):
        self.detail.quantity = 50
        self.detail.save()
        self.assertEqual(Decimal(self.positions()[0]["price"].replace(",", ".")), Decimal("153.40"))

    def test_active_special_price_takes_precedence(self):
        self.price.special_price = Decimal("130.00")
        self.price.special_start_date = timezone.now() - timedelta(days=1)
        self.price.special_end_date = timezone.now() + timedelta(days=1)
        self.price.save()
        self.assertEqual(Decimal(self.positions()[0]["price"].replace(",", ".")), Decimal("130.00"))

    def test_other_channel_and_other_factor_keep_shopware_price(self):
        self.order.sales_channel_id = "de-test"
        self.order.save()
        self.assertEqual(self.positions()[0]["price"], "1,45")
        self.order.sales_channel_id = "ch-test"
        self.order.save()
        self.product.factor = 5
        self.product.save()
        self.assertEqual(self.positions()[0]["price"], "1,45")

    def test_missing_channel_price_fails_instead_of_using_another_channel(self):
        self.price.sales_channel = ShopwareSettings.objects.create(name="DE test", sales_channel_id="de-test")
        self.price.save()
        with self.assertRaisesRegex(ValueError, "Kein Bridge-Preis"):
            self.positions()

    def test_builder_exposes_both_sources(self):
        paths = {field.path for field in get_order_detail_field_defs()}
        self.assertTrue({"product__factor", "bridge_price"} <= paths)
