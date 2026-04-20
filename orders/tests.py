from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from customer.models import Address, Customer
from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
)
from orders.models import Order
from orders.services.order_rule_resolver import (
    OrderRuleResolverService,
    ResolvedDatasetAction,
    ResolvedOrderRule,
)
from orders.services.order_upsert_microtech import OrderRuleDebugInfo, OrderUpsertMicrotechService


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
            name="Testkunde GmbH",
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

    def test_django_field_conditions_collect_dataset_actions(self):
        order = self._create_order(
            api_id="A1",
            payment_method="PayPal Plus",
            shipping_country="AT",
        )

        vorgang_dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgang_vorgange",
            name="Vorgang",
            description="Vorgange",
            source_identifier="Vorgang - Vorgange",
            priority=10,
        )
        vorgang_field = MicrotechDatasetField.objects.create(
            dataset=vorgang_dataset,
            field_name="ZahlArt",
            label="Zahlungsart",
            field_type="Integer",
            priority=10,
        )

        rule = MicrotechOrderRule.objects.create(
            name="AT + PayPal",
            priority=1,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            django_field_path="payment_method",
            operator_code="contains",
            expected_value="paypal",
            priority=1,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            django_field_path="shipping_address__country_code",
            operator_code="eq",
            expected_value="AT",
            priority=2,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            action_type=MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION,
            target_value="P",
            priority=1,
        )
        MicrotechOrderRuleAction.objects.create(
            rule=rule,
            action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset=vorgang_dataset,
            dataset_field=vorgang_field,
            target_value="22",
            priority=2,
        )

        resolved = OrderRuleResolverService().resolve_for_order(order=order)

        self.assertEqual(resolved.rule_id, rule.id)
        self.assertEqual(len(resolved.dataset_actions), 2)
        self.assertEqual(resolved.dataset_actions[0].action_type, MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION)
        self.assertEqual(resolved.dataset_actions[1].dataset_field_name, "ZahlArt")
        self.assertEqual(resolved.dataset_actions[1].target_value, "22")

    def test_equals_alias_matches_like_eq(self):
        order = self._create_order(
            api_id="A1-EQUALS",
            shipping_country="AT",
        )

        rule = MicrotechOrderRule.objects.create(
            name="AT via equals alias",
            priority=1,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=rule,
            django_field_path="shipping_address__country_code",
            operator_code="equals",
            expected_value="AT",
            priority=1,
        )

        resolved = OrderRuleResolverService().resolve_for_order(order=order)

        self.assertEqual(resolved.rule_id, rule.id)

    def test_invalid_django_field_path_does_not_match_and_fallback_rule_wins(self):
        order = self._create_order(api_id="A2")

        invalid_rule = MicrotechOrderRule.objects.create(
            name="Invalid field rule",
            priority=1,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        MicrotechOrderRuleCondition.objects.create(
            rule=invalid_rule,
            django_field_path="not_existing_field",
            operator_code="eq",
            expected_value="x",
            priority=1,
        )

        fallback_rule = MicrotechOrderRule.objects.create(
            name="Fallback",
            priority=2,
            is_active=True,
            condition_logic=MicrotechOrderRule.ConditionLogic.ALL,
        )

        resolved = OrderRuleResolverService().resolve_for_order(order=order)

        self.assertEqual(resolved.rule_id, fallback_rule.id)


class OrderUpsertRuleDebugTest(SimpleTestCase):
    def test_payment_position_missing_amount_uses_default_article_price(self):
        order = SimpleNamespace(order_number="ORDER-TRACE")
        so_vorgang = SimpleNamespace(Positionen=SimpleNamespace(Add=lambda *args, **kwargs: None))
        resolved_rule = ResolvedOrderRule(
            rule_id=42,
            rule_name="PayPal Regel",
            add_payment_position=True,
            payment_position_erp_nr="P",
        )

        debug = OrderUpsertMicrotechService()._add_payment_position(
            order=order,
            so_vorgang=so_vorgang,
            resolved_rule=resolved_rule,
        )

        self.assertTrue(debug.payment_position_requested)
        self.assertTrue(debug.payment_position_added)
        self.assertEqual(debug.payment_position_erp_nr, "P")
        self.assertIn("ohne Preisanpassung", debug.payment_position_reason)

    def test_rule_debug_info_dataclass_is_constructible(self):
        debug = OrderRuleDebugInfo(
            rule_id=1,
            rule_name="Fallback",
            payment_position_requested=False,
            payment_position_added=False,
            payment_position_reason="Keine Zusatzposition gefordert.",
            payment_position_erp_nr="",
        )

        self.assertEqual(debug.rule_id, 1)
        self.assertEqual(debug.rule_name, "Fallback")

    def test_build_export_metadata_text_contains_tariff_and_weights(self):
        text = OrderUpsertMicrotechService._build_export_metadata_text(
            customs_tariff_number="1234.56",
            weight_gross=Decimal("1.2500"),
            weight_net=Decimal("1.1000"),
        )

        self.assertEqual(
            text,
            "Statistische Warennummer: 1234.56\nGewicht brutto: 1,25 kg\nGewicht netto: 1,1 kg",
        )

    def test_append_export_metadata_to_position_name_only_for_swiss_orders(self):
        text = OrderUpsertMicrotechService._append_export_metadata_to_position_name(
            "Artikel A",
            "Statistische Warennummer: 1234\nGewicht brutto: 2 kg",
            append_customs_metadata=True,
        )

        self.assertEqual(
            text,
            "Artikel A\nStatistische Warennummer: 1234\nGewicht brutto: 2 kg",
        )

        unchanged = OrderUpsertMicrotechService._append_export_metadata_to_position_name(
            "Artikel A",
            "Statistische Warennummer: 1234",
            append_customs_metadata=False,
        )
        self.assertEqual(unchanged, "Artikel A")

    def test_duplicate_create_extra_position_actions_are_applied_once_per_erp_nr(self):
        calls: list[tuple[int, str, str]] = []

        def add_position(quantity, unit, erp_nr):
            calls.append((quantity, unit, erp_nr))

        order = SimpleNamespace(order_number="ORDER-TRACE")
        so_vorgang = SimpleNamespace(
            Positionen=SimpleNamespace(
                Add=add_position,
                DataSet=SimpleNamespace(),
            )
        )
        resolved_rule = ResolvedOrderRule(
            rule_id=42,
            rule_name="P dedupe",
            dataset_actions=(
                ResolvedDatasetAction(
                    action_type=MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION,
                    target_value="P",
                ),
                ResolvedDatasetAction(
                    action_type=MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION,
                    target_value="P",
                ),
                ResolvedDatasetAction(
                    action_type=MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION,
                    target_value="Q",
                ),
            ),
        )

        debug = OrderUpsertMicrotechService()._apply_rule_dataset_actions(
            order=order,
            so_vorgang=so_vorgang,
            resolved_rule=resolved_rule,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(debug.create_position_requested, 3)
        self.assertEqual(debug.create_position_applied, 2)
        self.assertEqual(debug.created_position_erp_nrs, ("P", "Q"))

    def test_set_dataset_field_uses_integer_writer_for_integer_catalog_type(self):
        field = SimpleNamespace(FieldType="", AsInteger=None, AsString=None, AsFloat=None, Text=None)
        dataset = SimpleNamespace(Fields=SimpleNamespace(Item=lambda name: field))

        written = OrderUpsertMicrotechService._set_dataset_field(
            dataset=dataset,
            field_name="ZahlArt",
            value="22",
            field_type_hint="Integer",
        )

        self.assertTrue(written)
        self.assertEqual(field.AsInteger, 22)
        self.assertIsNone(field.AsString)

    def test_set_dataset_field_uses_string_writer_for_unicode_catalog_type(self):
        field = SimpleNamespace(FieldType="", AsInteger=None, AsString=None, AsFloat=None, Text=None)
        dataset = SimpleNamespace(Fields=SimpleNamespace(Item=lambda name: field))

        written = OrderUpsertMicrotechService._set_dataset_field(
            dataset=dataset,
            field_name="KuBez",
            value="PayPal Gebuehr",
            field_type_hint="UnicodeString",
        )

        self.assertTrue(written)
        self.assertEqual(field.AsString, "PayPal Gebuehr")
        self.assertIsNone(field.AsInteger)

    @patch.object(OrderUpsertMicrotechService, "_clear_erp_order_id")
    @patch.object(OrderUpsertMicrotechService, "_persist_erp_order_id")
    @patch.object(OrderUpsertMicrotechService, "_find_beleg_nr_by_auftr_nr", return_value="BN-2000")
    @patch("orders.services.order_upsert_microtech.MicrotechVorgangService")
    def test_refresh_erp_order_id_uses_order_number_as_auftr_nr_fallback(
        self,
        vorgang_service_cls,
        find_beleg_nr_by_auftr_nr_mock,
        persist_erp_order_id_mock,
        clear_erp_order_id_mock,
    ):
        order = Order(
            api_id="order-1",
            order_number="SW-10001",
            erp_order_id="BN-1000",
        )
        vorgang_service = vorgang_service_cls.return_value
        vorgang_service.find.return_value = False

        refreshed = OrderUpsertMicrotechService().refresh_erp_order_id(order, erp=object())

        self.assertEqual(refreshed, "BN-2000")
        find_beleg_nr_by_auftr_nr_mock.assert_called_once_with(
            vorgang_service=vorgang_service,
            auftr_nr="SW-10001",
            customer_erp_nr="",
        )
        persist_erp_order_id_mock.assert_called_once_with(order=order, erp_order_id="BN-2000")
        clear_erp_order_id_mock.assert_not_called()
