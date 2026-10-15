from copy import deepcopy

from django.test import SimpleTestCase

from orders.services.order_price import OrderPriceService


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

    def test_unit_prices_stay_exact_even_for_subcent_differences(self):
        for gross in (False, True):
            with self.subTest(gross=gross):
                manifest = deepcopy(self.expected)
                manifest["gross"] = gross
                result = deepcopy(self.result)
                position = result["vorgang"]["positions"][0]
                position["grossTotalPrice"] = "100.00"
                position["grossUnitPrice" if gross else "unitPrice"] = "100.001"
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
