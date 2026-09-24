import json
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase
from django.test.client import RequestFactory

from microtech.admin import MicrotechOrderRuleAdmin
from microtech.models import MicrotechDatasetCatalog, MicrotechDatasetField, MicrotechOrderRule
from microtech.rule_field_labels import (
    graphql_field_ui_label,
    graphql_microtech_field_target,
    microtech_field_ui_label,
    microtech_list_labels,
    shop_field_paths_matching_api,
    shop_field_ui_label,
)


class RuleFieldUiLabelTest(SimpleTestCase):
    def test_shopware_order_field_uses_api_name(self):
        self.assertEqual(
            shop_field_ui_label("order_number", "Order - Bestellnummer (order_number)"),
            "Bestellung: orderNumber - Bestellnummer",
        )
        self.assertEqual(
            shop_field_ui_label("purchase_date", "Bestelldatum"),
            "Bestellung: createdAt - Bestelldatum",
        )
        self.assertIn("order_number", shop_field_paths_matching_api("orderNumber"))

    def test_shopware_nested_fields_keep_their_scope(self):
        self.assertEqual(
            shop_field_ui_label(
                "shipping_address__postal_code",
                "Lieferanschrift - PLZ (shipping_address__postal_code)",
            ),
            "Lieferanschrift: deliveries[0].shippingOrderAddress.zipcode - PLZ",
        )
        self.assertEqual(
            shop_field_ui_label(
                "quantity", "Bestellposition - Menge (quantity)",
                context_root="orders.OrderDetail",
            ),
            "Bestellposition: lineItems[].quantity - Menge",
        )

    def test_bridge_only_values_are_not_claimed_as_shopware_api_fields(self):
        self.assertEqual(
            shop_field_ui_label("erp_order_id", "Order - Microtech BelegNr (erp_order_id)"),
            "Bestellung (Bridge): erp_order_id - Microtech BelegNr",
        )
        self.assertEqual(
            shop_field_ui_label("code_values__vorgangArt", "Bisheriges Mapping - vorgangArt (code_values__vorgangArt)"),
            "Bridge-Mapping: vorgangArt",
        )
        self.assertEqual(
            shop_field_ui_label(
                "factor", "Artikel - Faktor (factor)", context_root="products.Product"
            ),
            "Artikel (Bridge): factor - Faktor",
        )

    def test_microtech_field_uses_abbreviation_and_catalog_description(self):
        self.assertEqual(microtech_field_ui_label("ZahlArt", "Zahlungsart"), "ZahlArt - Zahlungsart")
        self.assertEqual(microtech_field_ui_label("Bez", ""), "Bez")
        self.assertEqual(microtech_list_labels()[("Vorgang", "ZahlArt")], "Zahlungsart")
        dataset = MicrotechDatasetCatalog(id=1, name="Vorgang")
        field = MicrotechDatasetField(dataset=dataset, field_name="ZahlArt", label="Altes Label")
        self.assertEqual(field.display_label, "ZahlArt - Zahlungsart")

    def test_graphql_field_label_uses_the_matching_list_entry(self):
        self.assertEqual(
            graphql_microtech_field_target("PostalAddressInput", "zipCode"),
            ("Anschriften", "PLZ"),
        )
        self.assertEqual(
            graphql_field_ui_label(
                "PostalAddressInput", "zipCode", "",
                {("Anschriften", "PLZ"): "Postleitzahl"},
            ),
            "PLZ - Postleitzahl",
        )
        self.assertEqual(
            graphql_field_ui_label("VorgangInput", "currency", "", {}),
            "currency (GraphQL)",
        )

    def test_graphql_dropdown_uses_catalog_label_without_changing_field_value(self):
        admin = MicrotechOrderRuleAdmin(MicrotechOrderRule, AdminSite())
        request = RequestFactory().get("/admin/microtech/rule-fields/")
        catalog = {
            "ok": True,
            "source": "introspection",
            "groups": [{
                "input_type": "PostalAddressInput",
                "label": "Anschrift",
                "fields": [{"name": "zipCode", "description": ""}],
            }],
        }
        with (
            patch.object(admin, "has_view_permission", return_value=True),
            patch("microtech.graphql_schema.get_graphql_input_catalog", return_value=catalog),
            patch("microtech.admin.microtech_list_labels", return_value={
                ("Anschriften", "PLZ"): "Postleitzahl",
            }),
        ):
            response = admin.rule_graphql_fields_grouped_view(request)

        field = json.loads(response.content)["groups"][0]["fields"][0]
        self.assertEqual(field["name"], "zipCode")
        self.assertEqual(field["ui_label"], "PLZ - Postleitzahl")
