from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, localcontext
from types import SimpleNamespace

from django.test import SimpleTestCase

from orders.services.order_price import OrderPriceService
from orders.services.order_sync import _to_decimal


class OrderImportRoundingTest(SimpleTestCase):
    def test_import_and_export_agree_on_subcent_tax_free_order(self):
        detail = SimpleNamespace(api_id="line", erp_nr="204113", quantity=250)
        order = SimpleNamespace(
            total_price=_to_decimal("140.825"),
            shopware_price_snapshot={
                "version": 1, "currency": "EUR",
                "price": {"taxStatus": "tax-free", "totalPrice": "140.825"},
                "shipping": {"totalPrice": "9.95"},
                "lines": [{"id": "line", "quantity": 250,
                           "price": {"unitPrice": "0.5235", "totalPrice": "130.875"}}],
            },
            details=SimpleNamespace(all=lambda: [detail]),
        )
        detail.order = order
        self.assertEqual(order.total_price, Decimal("140.83"))
        OrderPriceService().validate_snapshot(order)

    def test_import_rounding_is_independent_of_decimal_context(self):
        with localcontext() as context:
            context.rounding = ROUND_DOWN
            for raw, expected in (("140.825", "140.83"), ("130.875", "130.88"),
                                  ("-1.005", "-1.01"), ("9.95", "9.95")):
                with self.subTest(raw=raw):
                    self.assertEqual(_to_decimal(raw), Decimal(expected))


class OrderPriceRoundingTest(SimpleTestCase):
    def setUp(self):
        self.pricing = OrderPriceService()
        self.expected = {
            "gross": False,
            "currency": "EUR",
            "netto": "100.00",
            "brutto": "119.00",
            "positions": [{
                "erpNumber": "214025", "quantity": "100",
                "unitPrice": "1.00", "totalPrice": "100.00",
            }],
        }
        self.result = {"vorgang": {
            "belegNr": "TEST/1", "currency": "EUR",
            "netto": "100.00", "brutto": "119.00",
            "positions": [{
                "erpNumber": "214025", "quantity": "100", "unit": "% Stck",
                "unitPrice": "100.00", "totalPrice": "100.00",
                "grossUnitPrice": "119.00", "grossTotalPrice": "119.00",
            }],
        }}

    def test_production_rounding_differences_pass(self):
        for expected, actual in (
            ("202.23", "202.2386"), ("102.34", "102.3462"),
            ("66.03", "66.021"), ("22.51", "22.5042"),
            ("171.96", "171.95499999999998"),
        ):
            with self.subTest(expected=expected, actual=actual):
                manifest = deepcopy(self.expected)
                manifest["netto"] = expected
                result = deepcopy(self.result)
                result["vorgang"]["netto"] = actual
                self.pricing.verify_export(manifest, result)

    def test_header_totals_allow_one_cent_in_both_directions(self):
        for field, values in (("netto", ("99.99", "100.01")),
                              ("brutto", ("118.99", "119.01"))):
            for value in values:
                with self.subTest(field=field, value=value):
                    result = deepcopy(self.result)
                    result["vorgang"][field] = value
                    checked = self.pricing.verify_export(self.expected, result)
                    self.assertEqual(checked[field], value)

    def test_header_totals_reject_two_cents_in_both_directions(self):
        for field, values in (("netto", ("99.98", "100.02")),
                              ("brutto", ("118.98", "119.02"))):
            for value in values:
                with self.subTest(field=field, value=value):
                    result = deepcopy(self.result)
                    result["vorgang"][field] = value
                    with self.assertRaisesRegex(ValueError, f"Microtech-{field}"):
                        self.pricing.verify_export(self.expected, result)

    def test_position_totals_allow_one_cent_for_net_and_gross_orders(self):
        for gross in (False, True):
            for value in ("99.99", "100.01"):
                with self.subTest(gross=gross, value=value):
                    manifest = deepcopy(self.expected)
                    manifest["gross"] = gross
                    result = deepcopy(self.result)
                    position = result["vorgang"]["positions"][0]
                    position["grossUnitPrice"] = "100.00"
                    position["grossTotalPrice" if gross else "totalPrice"] = value
                    self.pricing.verify_export(manifest, result)

    def test_position_totals_reject_two_cents_for_net_and_gross_orders(self):
        for gross in (False, True):
            for value in ("99.98", "100.02"):
                with self.subTest(gross=gross, value=value):
                    manifest = deepcopy(self.expected)
                    manifest["gross"] = gross
                    result = deepcopy(self.result)
                    position = result["vorgang"]["positions"][0]
                    position["grossUnitPrice"] = "100.00"
                    position["grossTotalPrice" if gross else "totalPrice"] = value
                    with self.assertRaisesRegex(ValueError, "Preisabweichung"):
                        self.pricing.verify_export(manifest, result)

    def test_unit_price_rounding_is_limited_to_one_cent_for_the_whole_line(self):
        for gross in (False, True):
            for value in ("100.001", "100.01", "99.99", "100.02", "99.98"):
                with self.subTest(gross=gross, value=value):
                    manifest = deepcopy(self.expected)
                    manifest["gross"] = gross
                    result = deepcopy(self.result)
                    position = result["vorgang"]["positions"][0]
                    position["grossTotalPrice"] = "100.00"
                    position["grossUnitPrice" if gross else "unitPrice"] = value
                    if value in ("100.02", "99.98"):
                        with self.assertRaisesRegex(ValueError, "Preisabweichung"):
                            self.pricing.verify_export(manifest, result)
                    else:
                        self.pricing.verify_export(manifest, result)

    def test_converted_invoice_brutto_unit_price_can_have_subcent_precision(self):
        manifest = deepcopy(self.expected)
        manifest["gross"] = True
        manifest["positions"][0].update(quantity="1", unitPrice="5.47", totalPrice="5.47")
        result = deepcopy(self.result)
        result["vorgang"]["positions"][0].update(
            quantity="1", unit="Blatt", grossUnitPrice="5.473999999999999",
            grossTotalPrice="5.473999999999999",
        )
        self.pricing.verify_export(manifest, result)

    def test_small_unit_difference_cannot_accumulate_beyond_one_cent(self):
        manifest = deepcopy(self.expected)
        manifest["positions"][0].update(quantity="1000", totalPrice="1000.00")
        result = deepcopy(self.result)
        position = result["vorgang"]["positions"][0]
        position.update(quantity="1000", unit="Stck", unitPrice="1.001", totalPrice="1000.00")
        with self.assertRaisesRegex(ValueError, "Preisabweichung"):
            self.pricing.verify_export(manifest, result)

    def test_additional_one_cent_position_is_still_rejected(self):
        result = deepcopy(self.result)
        result["vorgang"]["positions"].append({"erpNumber": "EXTRA", "totalPrice": "0.01"})
        with self.assertRaisesRegex(ValueError, "zusätzliche preiswirksame"):
            self.pricing.verify_export(self.expected, result)

    def test_wrong_article_quantity_currency_and_missing_totals_stay_invalid(self):
        for field, value in (("erpNumber", "WRONG"), ("quantity", "99"), ("totalPrice", None)):
            with self.subTest(field=field):
                result = deepcopy(self.result)
                result["vorgang"]["positions"][0][field] = value
                with self.assertRaisesRegex(ValueError, "Preisabweichung"):
                    self.pricing.verify_export(self.expected, result)
        for field, value in (("currency", "CHF"), ("netto", None), ("brutto", None)):
            with self.subTest(field=field):
                result = deepcopy(self.result)
                result["vorgang"][field] = value
                with self.assertRaises(ValueError):
                    self.pricing.verify_export(self.expected, result)
