from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from customer.models import Address, Customer
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
)
from orders.models import Order, OrderDetail
from orders.services.order_rule_resolver import (
    OrderRuleResolverService,
    ResolvedDatasetAction,
    ResolvedOrderRule,
)
from orders.services.order_upsert_microtech import OrderRuleDebugInfo, OrderUpsertMicrotechService
from orders.services.order_sync import OrderSyncService
from products.models import Product


class OrderGraphQLPayloadTest(SimpleTestCase):
    def test_shopware_company_address_keeps_contact_name_in_name2(self):
        imported_address = SimpleNamespace(api_id="", name1="", name2="", save=MagicMock())
        address_data = {
            "id": "sw-address-1",
            "company": "Muster GmbH",
            "firstName": "Max",
            "lastName": "Mustermann",
            "salutation": {"displayName": "Herr"},
            "country": {"iso": "DE"},
        }

        with (
            patch("orders.services.order_sync.Address", return_value=imported_address) as address_model,
            patch.object(OrderSyncService, "_find_contact_address", return_value=None),
        ):
            address_model.objects.filter.return_value.filter.return_value.first.return_value = None
            OrderSyncService()._upsert_address(
                customer=SimpleNamespace(erp_nr="1000"),
                address_data=address_data,
                fallback_email="",
                is_invoice=True,
                is_shipping=False,
            )

        self.assertEqual(imported_address.name1, "Muster GmbH")
        self.assertEqual(imported_address.name2, "Max Mustermann")

    def test_company_address_uses_firma_in_graphql_name1_and_company_in_name2(self):
        address = Address(
            name1="Muster GmbH",
            name2="Max Mustermann",
            title="Herr",
            first_name="Max",
            last_name="Mustermann",
        )

        payload = CustomerUpsertMicrotechService()._build_postal_address_input(
            address=address,
            is_shipping=True,
            is_invoice=False,
            na1_mode="auto",
            na1_static_value="",
        )

        self.assertEqual(payload["name1"], "Firma")
        self.assertEqual(payload["name2"], "Muster GmbH")

    def test_graphql_decimal_uses_german_decimal_separator(self):
        self.assertEqual(OrderUpsertMicrotechService._format_graphql_decimal(Decimal("15.00")), "15,00")
        self.assertEqual(OrderUpsertMicrotechService._format_graphql_decimal(Decimal("1.235")), "1,24")
        self.assertEqual(OrderUpsertMicrotechService._format_graphql_decimal(None), "")

    def test_order_details_are_sorted_by_article_number(self):
        details = [
            SimpleNamespace(erp_nr="ART-20", pk=1),
            SimpleNamespace(erp_nr="ART-3", pk=2),
            SimpleNamespace(erp_nr="ART-100", pk=3),
        ]

        ordered = OrderUpsertMicrotechService._sort_order_details(details)

        self.assertEqual([detail.erp_nr for detail in ordered], ["ART-3", "ART-20", "ART-100"])

    def test_special_positions_always_include_a_vorgang_unit(self):
        positions: list[dict[str, str]] = []
        resolved_rule = ResolvedOrderRule(
            rule_id=6,
            rule_name="P fuer PayPal",
            dataset_actions=(
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

        OrderUpsertMicrotechService()._build_graphql_rule_debug(
            order=SimpleNamespace(order_number="ORDER-TRACE"),
            resolved_rule=resolved_rule,
            positions=positions,
        )

        self.assertEqual(
            positions,
            [
                {"erpNumber": "P", "quantity": "1", "unit": "Stück"},
                {"erpNumber": "Q", "quantity": "1", "unit": "Stück"},
            ],
        )

    def test_shipping_rule_uses_selected_article_and_order_shipping_costs(self):
        order = SimpleNamespace(
            details=SimpleNamespace(all=lambda: []),
            shipping_costs=Decimal("4.95"),
            billing_address=None,
        )
        resolved_rule = ResolvedOrderRule(
            rule_id=7,
            rule_name="F fuer Spedition",
            dataset_actions=(
                ResolvedDatasetAction(
                    action_type=MicrotechOrderRuleAction.ActionType.CREATE_SHIPPING_POSITION,
                    target_value="F",
                ),
            ),
        )

        positions, rule_debug = OrderUpsertMicrotechService()._build_graphql_positions(
            order=order,
            resolved_rule=resolved_rule,
            client=MagicMock(),
        )

        self.assertEqual(
            positions,
            [{"erpNumber": "F", "quantity": "1", "unit": "Stück", "price": "4,95"}],
        )
        self.assertEqual(rule_debug.dataset_actions_applied, 1)

    def test_erp_order_id_fallback_uses_graphql_filter_string(self):
        customer = Customer(erp_nr="1000")
        order = Order(api_id="order-1", order_number="SW-'10001", customer=customer)
        client = MagicMock()
        client.poll_dataset_records.return_value = {
            "records": [{"BelegNr": "BN-2000", "AuftrNr": "SW-'10001", "AdrNr": "1000"}]
        }

        with patch.object(OrderUpsertMicrotechService, "_persist_erp_order_id"):
            result = OrderUpsertMicrotechService()._refresh_erp_order_id_graphql(order=order, client=client)

        self.assertEqual(result, "BN-2000")
        request_payload = client.poll_dataset_records.call_args.args[0]
        self.assertEqual(request_payload["filter"], "AuftrNr = 'SW-''10001'")
        self.assertNotIn("filters", request_payload)


class OrderNetPriceTest(SimpleTestCase):
    def test_gross_shopware_price_is_converted_to_net_unit_price(self):
        price = OrderSyncService._net_unit_price_from_shopware_price(
            {
                "unitPrice": "11.90",
                "totalPrice": "23.80",
                "calculatedTaxes": [{"tax": "3.80"}],
            },
            quantity=2,
            tax_status="gross",
        )

        self.assertEqual(price, Decimal("10.00"))

    def test_net_shopware_price_is_kept_as_net_unit_price(self):
        price = OrderSyncService._net_unit_price_from_shopware_price(
            {"unitPrice": "10.00", "totalPrice": "20.00", "calculatedTaxes": [{"tax": "3.80"}]},
            quantity=2,
            tax_status="net",
        )

        self.assertEqual(price, Decimal("10.00"))


class OrderSyncWorkflowEnqueueTest(SimpleTestCase):
    def test_import_does_not_start_microtech_workflow(self):
        service = OrderSyncService()
        customer = SimpleNamespace()
        billing_address = SimpleNamespace()
        shipping_address = SimpleNamespace()
        order = SimpleNamespace(pk=42)
        workflow = SimpleNamespace(pk=73)
        order_data = {
            "id": "shopware-order-1",
            "price": {"taxStatus": "net", "totalPrice": "10.00", "calculatedTaxes": []},
            "deliveries": [{"id": "delivery-1"}],
            "transactions": [{"id": "transaction-1"}],
            "lineItems": [],
        }

        with (
            patch.object(
                service,
                "_upsert_customer_block",
                return_value=(customer, billing_address, shipping_address, 2),
            ),
            patch.object(service, "_replace_order_details", return_value=0),
            patch(
                "orders.services.order_sync.Order.objects.update_or_create",
                return_value=(order, True),
            ),
            patch(
                "orders.services.order_sync_workflow.OrderSyncWorkflowService.ensure_pending_for_order",
                return_value=(workflow, True),
            ) as ensure_pending,
            patch("orders.services.order_sync.transaction.on_commit") as on_commit,
        ):
            result = OrderSyncService.upsert_from_shopware_order.__wrapped__(
                service,
                order_data=order_data,
            )

        # Der Export nach Microtech wird ausschliesslich manuell gestartet.
        self.assertFalse(result["workflow_created"])
        self.assertIsNone(result["workflow_id"])
        ensure_pending.assert_not_called()
        on_commit.assert_not_called()


class OrderProductNumberResolutionTest(TestCase):
    def setUp(self):
        self.order = Order.objects.create(api_id="order-product-number-resolution")
        self.product = Product.objects.create(
            erp_nr="ERP-ARTICLE-42",
            sku="shopware-product-42",
        )

    def test_product_position_uses_django_erp_number_from_shopware_product_id(self):
        created = OrderSyncService()._replace_order_details(
            order=self.order,
            line_items=[
                {
                    "id": "line-item-42",
                    "type": "product",
                    "referencedId": self.product.sku,
                    "payload": {"productNumber": "ERP-ARTICLE-42"},
                    "label": "Artikel 42",
                    "quantity": 1,
                    "price": {"unitPrice": "10.00", "totalPrice": "10.00"},
                }
            ],
            tax_status="net",
        )

        self.assertEqual(created, 1)
        self.assertEqual(self.order.details.get().erp_nr, "ERP-ARTICLE-42")

    def test_auto_generated_shopware_variant_number_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "kann keiner Django-Artikelnummer zugeordnet werden"):
            OrderSyncService()._replace_order_details(
                order=self.order,
                line_items=[
                    {
                        "id": "line-item-duplicate",
                        "type": "product",
                        "referencedId": "shopware-duplicate-variant",
                        "payload": {"productNumber": "PARENT-STRIP-TABS.33"},
                        "label": "Doppelte Variante",
                        "quantity": 1,
                        "price": {"unitPrice": "10.00", "totalPrice": "10.00"},
                    }
                ],
                tax_status="net",
            )

        self.assertFalse(self.order.details.exists())


class OrderPositionUnitTest(TestCase):
    """Die Mengeneinheit einer Vorgangsposition stammt aus dem Microtech-Artikel."""

    def setUp(self):
        self.order = Order.objects.create(api_id="order-factor-unit", order_number="ORDER-FACTOR")
        self.detail = OrderDetail.objects.create(
            order=self.order,
            erp_nr="ERP-FACTOR-1",
            name="Faktorartikel",
            unit="Pack",
            quantity=2,
            unit_price=Decimal("10.00"),
            total_price=Decimal("20.00"),
        )

    def _build_positions(self, *, microtech_unit: str = "Karton"):
        with patch(
            "orders.services.order_upsert_microtech.MicrotechArtikelService"
        ) as artikel_service_cls:
            artikel_service_cls.return_value.find.return_value = True
            artikel_service_cls.return_value.get_unit.return_value = microtech_unit
            artikel_service_cls.return_value.get_name.return_value = "Faktorartikel"
            positions, _debug = OrderUpsertMicrotechService()._build_graphql_positions(
                order=self.order,
                resolved_rule=ResolvedOrderRule(rule_id=None, rule_name=""),
                client=MagicMock(),
            )
        return positions

    def test_unit_is_read_from_the_microtech_article(self):
        Product.objects.create(erp_nr="ERP-FACTOR-1", sku="sku-factor-1", unit="Pack")

        positions = self._build_positions()

        self.assertEqual(positions[0]["unit"], "Karton")

    def test_factor_does_not_change_the_microtech_article_unit(self):
        Product.objects.create(erp_nr="ERP-FACTOR-1", sku="sku-factor-1", factor=5, unit="Pack")

        positions = self._build_positions()

        self.assertEqual(positions[0]["unit"], "Karton")

    def test_article_unit_falls_back_to_the_product_record(self):
        Product.objects.create(erp_nr="ERP-FACTOR-1", sku="sku-factor-1", factor=5, unit="Pack")

        positions = self._build_positions(microtech_unit="")

        self.assertEqual(positions[0]["unit"], "Pack")


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
