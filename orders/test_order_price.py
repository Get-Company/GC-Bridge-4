from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from microtech.models import (MicrotechOrderRule, MicrotechOrderRuleAction,
                             MicrotechOrderRuleCondition, MicrotechOrderRuleConditionGroup, RuleTrigger)
from microtech.rule_engine.mapping_resolver import ORDER_POSITION_MAPPING_TASK
from orders.models import Order, OrderDetail, MicrotechOrderSyncWorkflow
from orders.services.order_price import OrderPriceService
from orders.services.order_sync import OrderSyncService
from orders.services.order_rule_resolver import ResolvedOrderRule
from orders.services.order_upsert_microtech import OrderUpsertMicrotechService
from orders.services.order_sync_workflow import OrderSyncWorkflowService
from products.models import Product, Price
from shopware.models import ShopwareSettings


class OrderPriceTest(TestCase):
    def setUp(self):
        self.data = {"id": "shopware-original", "currency": {"isoCode": "EUR"},
                     "price": {"taxStatus": "tax-free", "netPrice": "144.80", "totalPrice": "144.80"},
                     "shippingCosts": {"totalPrice": "0.00"},
                     "lineItems": [{"id": "line-1", "quantity": 100, "type": "product",
                                    "price": {"unitPrice": "1.448", "totalPrice": "144.80"}}]}
        self.order = Order.objects.create(api_id="shopware-original", sales_channel_id="ch", total_price="144.80",
                                          shopware_price_snapshot=OrderPriceService.snapshot_from_data(self.data))
        self.detail = OrderDetail.objects.create(order=self.order, api_id="line-1", erp_nr="214025", quantity=100,
                                                 unit_price="1.45", total_price="144.80")
        self.product = Product.objects.create(erp_nr="214025", sku="test-214025", factor=100, unit="Stck")
        trigger, _ = RuleTrigger.objects.get_or_create(task_name=ORDER_POSITION_MAPPING_TASK,
                                                       defaults={"label": "Position", "context_root": "orders.OrderDetail"})
        self.rule = MicrotechOrderRule.objects.create(name="Shopware price per 100", trigger=trigger,
                                                       engine_enabled=True, shadow_mode=False)
        group = MicrotechOrderRuleConditionGroup.objects.create(rule=self.rule, logic="all")
        MicrotechOrderRuleCondition.objects.create(rule=self.rule, group=group, django_field_path="product__factor",
                                                    operator_code="eq", expected_value="100")
        for field, value in (("price", "{{ shopware_price_per_100 }}"), ("unit", "% Stck")):
            MicrotechOrderRuleAction.objects.create(rule=self.rule, graphql_field=f"VorgangPositionInput.{field}",
                                                    target_scope="position", target_value=value)
        self.pricing = OrderPriceService()

    def positions(self):
        return OrderUpsertMicrotechService()._build_graphql_positions(
            order=self.order, resolved_rule=ResolvedOrderRule(rule_id=None, rule_name=""),
            client=None, allow_remote_article_lookup=False)[0]

    def result(self):
        return {"vorgang": {"belegNr": "TEST/1", "currency": "EUR", "netto": "144.80", "brutto": "144.80",
                            "positions": [{"erpNumber": "214025", "quantity": "100", "unit": "% Stck",
                                           "unitPrice": "144.80", "totalPrice": "144.80"}]}}

    def test_rule_preserves_the_ordered_price_for_every_channel(self):
        for channel in ("de", "ch", "third-channel"):
            with self.subTest(channel=channel):
                self.order.sales_channel_id = channel
                self.order.save()
                position = self.positions()[0]
                self.assertEqual(Decimal(position["price"].replace(",", ".")), Decimal("144.800"))
                self.assertEqual(position["unit"], "% Stck")
                self.assertFalse(position["priceIsGross"])

    def test_changed_catalogue_prices_cannot_change_the_completed_order(self):
        channel = ShopwareSettings.objects.create(name="CH", sales_channel_id="ch")
        Price.objects.create(product=self.product, sales_channel=channel, price="999.99", special_price="888.88")
        self.assertEqual(Decimal(self.positions()[0]["price"].replace(",", ".")), Decimal("144.8"))

    def test_non_factor_price_keeps_all_decimals_without_percent_unit(self):
        self.product.factor = 0
        self.product.save()
        position = self.positions()[0]
        self.assertEqual(position["price"], "1,448")
        self.assertEqual(position["unit"], "Stck")

    def test_rule_cannot_silently_double_divide_or_replace_the_price(self):
        self.rule.actions.filter(graphql_field="VorgangPositionInput.price").update(target_value="1.448")
        with self.assertRaisesRegex(ValueError, "Regel-Mapping verändert"):
            self.positions()

    def test_gross_order_preserves_gross_precision_and_price_basis(self):
        self.data["price"] = {"taxStatus": "gross", "netPrice": "412.52", "totalPrice": "490.90"}
        self.data["lineItems"][0]["quantity"] = 1000
        self.data["lineItems"][0]["price"] = {"unitPrice": "0.4909", "totalPrice": "490.90"}
        self.order.total_price = Decimal("490.90")
        self.order.shopware_price_snapshot = self.pricing.snapshot_from_data(self.data)
        self.order.save()
        self.detail.quantity = 1000
        self.detail.save()
        self.pricing.validate_snapshot(self.order)
        position = self.positions()[0]
        self.assertTrue(position["priceIsGross"])
        self.assertEqual(Decimal(position["price"].replace(",", ".")), Decimal("49.09"))

    def test_import_preserves_subcent_unit_prices_and_tax_precision(self):
        self.assertEqual(OrderSyncService._net_unit_price_from_shopware_price(
            {"unitPrice": "1.448", "totalPrice": "144.80"}, quantity=100, tax_status="net"), Decimal("1.448"))
        self.assertEqual(OrderSyncService._net_unit_price_from_shopware_price(
            {"unitPrice": "0.4909", "totalPrice": "490.90", "calculatedTaxes": [{"tax": "78.379"}]},
            quantity=1000, tax_status="gross"), Decimal("0.412521"))

    def test_missing_legacy_snapshot_is_loaded_from_completed_order_not_product(self):
        self.order.shopware_price_snapshot = {}
        self.order.save()
        with patch("shopware.services.OrderService") as client:
            client.return_value.get_by_id.return_value = {"data": [self.data]}
            self.pricing.ensure_snapshot(self.order)
            client.return_value.get_by_id.assert_called_once_with("shopware-original")
        self.order.refresh_from_db()
        self.assertEqual(self.pricing.unit_price(self.detail), Decimal("1.448"))

    def test_incomplete_or_different_order_is_rejected_before_export(self):
        self.order.shopware_price_snapshot["lines"][0]["quantity"] = 101
        with self.assertRaisesRegex(ValueError, "Artikel/Menge"):
            self.pricing.validate_snapshot(self.order)

    def test_remote_verification_requires_unit_position_and_header_prices(self):
        expected = self.pricing.expected_export(self.order, self.positions())
        checked = self.pricing.verify_export(expected, self.result())
        self.assertEqual(checked["positions_checked"], 1)
        for field, value in (("unitPrice", "145"), ("totalPrice", "145")):
            result = self.result()
            result["vorgang"]["positions"][0][field] = value
            with self.assertRaisesRegex(ValueError, "Preisabweichung"):
                self.pricing.verify_export(expected, result)
        result = self.result()
        result["vorgang"]["brutto"] = "145"
        with self.assertRaisesRegex(ValueError, "brutto"):
            self.pricing.verify_export(expected, result)

    def test_shipping_uses_original_gross_order_price_not_net_display(self):
        self.data["price"] = {"taxStatus": "gross", "netPrice": "126.05", "totalPrice": "150.00"}
        self.data["shippingCosts"] = {"totalPrice": "5.20"}
        self.order.total_price = Decimal("150.00")
        self.order.shipping_costs = Decimal("4.37")
        self.order.shopware_price_snapshot = self.pricing.snapshot_from_data(self.data)
        self.order.save()
        self.pricing.validate_snapshot(self.order)
        shipping = self.positions()[1]
        self.assertEqual(shipping["price"], "5,20")
        self.assertTrue(shipping["priceIsGross"])

    def test_zero_price_does_not_trigger_catalogue_fallback(self):
        self.data["price"]["netPrice"] = self.data["price"]["totalPrice"] = "0.00"
        self.data["lineItems"][0]["price"] = {"unitPrice": "0", "totalPrice": "0"}
        self.order.total_price = 0
        self.order.shopware_price_snapshot = self.pricing.snapshot_from_data(self.data)
        self.order.save()
        self.pricing.validate_snapshot(self.order)
        self.assertEqual(Decimal(self.positions()[0]["price"].replace(",", ".")), Decimal(0))

    def test_verification_failure_keeps_existing_document_and_never_reports_success(self):
        expected = self.pricing.expected_export(self.order, self.positions())
        workflow = MicrotechOrderSyncWorkflow.objects.create(order=self.order, current_step="verify_vorgang_prices",
                                                              state={"beleg_nr": "TEST/1", "expected_prices": expected})
        result = self.result()
        result["vorgang"]["brutto"] = "145"
        with self.assertRaisesRegex(ValueError, "brutto"):
            OrderSyncWorkflowService()._apply_result(workflow, "verify_vorgang_prices", result)
        self.assertNotIn("price_verification", workflow.state)
        self.assertEqual(workflow.state["beleg_nr"], "TEST/1")
