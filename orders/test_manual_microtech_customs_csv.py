import csv
import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from microtech.customs_fields import DEFAULT_SWISS_CUSTOMS_FIELD_DEFINITIONS
from microtech.models import MicrotechSwissCustomsFieldMapping
from orders.admin import OrderAdmin
from orders.models import Order
from orders.services.swiss_customs_csv import SwissCustomsCsvExport, SwissCustomsCsvExportService


class ManualMicrotechCustomsCsvTest(SimpleTestCase):
    def setUp(self):
        product_filter = patch("orders.services.swiss_customs_csv.Product.objects.filter")
        self.bridge_product_filter = product_filter.start()
        self.addCleanup(product_filter.stop)
        self.bridge_product_filter.return_value.values_list.return_value = [("ART-1", "1234.56")]
        self.client = Mock()
        self.client.poll_dataset_records.side_effect = self._dataset_read
        self.client.request_vorgang.return_value = {
            "vorgang": {
                "belegNr": "26/1792",
                "orderNumber": "10387",
                "date": "2026-11-25",
                "positions": [
                    {"erpNumber": "ART-1", "name": "Ordner\r\nbrutto: 3 kg", "quantity": 2, "unit": "Stk", "unitPrice": 10, "totalPrice": 20},
                    {"erpNumber": "V", "name": "Versand", "quantity": 1, "unit": "Stk", "unitPrice": 5, "totalPrice": 5},
                ],
            },
        }
        self.client.request_product.return_value = {
            "product": {
                "name": "Ordner",
                "unit": "Stk",
                "customsTariffNumber": "WRONG-MICROTECH-VALUE",
                "weightGrossKg": "1.5",
                "weightNetKg": "1.2",
            },
        }

    @staticmethod
    def _dataset_read(payload, **kwargs):
        if payload["filter"] == "AuftrNr = '10387'":
            return {"records": [{"AuftrNr": "10387", "BelegNr": "26/1792", "AdrNr": "13747"}]}
        if payload["dataset"] == "Adressen":
            return {"records": [{"AdrNr": "13747", "UStId": "CHE-123.456.789"}]}
        return {
            "records": [{
                "BelegNr": "26/1792", "AuftrNr": "10387", "AdrNr": "13747",
                "LiNa1": "ACME GmbH", "LiNa2": "Max Mustermann",
                "LiStr": "Musterstrasse 7a", "LiPLZ": "8000", "LiOrt": "Zuerich",
                "LiLandKennz": "CH", "LiEMail1": "versand@example.com",
                "ReNa1": "ACME GmbH", "ReStr": "Rechnungsweg 3",
                "RePLZ": "8001", "ReOrt": "Zuerich", "ReLandKennz": "CH",
            }],
        }

    def test_export_uses_microtech_data_and_existing_mapping_without_bridge_order(self):
        mappings = [SimpleNamespace(**vars(item)) for item in DEFAULT_SWISS_CUSTOMS_FIELD_DEFINITIONS]
        with patch.object(MicrotechSwissCustomsFieldMapping.objects, "filter") as filtered:
            filtered.return_value.order_by.return_value = mappings
            export = SwissCustomsCsvExportService().export_microtech_order("10387", client=self.client)

        rows = list(csv.DictReader(io.StringIO(export.content)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(export.filename, "10387_Max_Mustermann.csv")
        self.assertEqual(rows[0]["invoice.invoiceNumber"], "26/1792")
        self.assertEqual(rows[0]["invoice.invoiceDate"], "25.11.2026")
        self.assertEqual(rows[0]["customerReference"], "13747")
        self.assertEqual(rows[0]["importer.taxId"], "CHE-123.456.789")
        self.assertEqual(rows[0]["importer.address.countryCode"], "CH")
        self.assertEqual(rows[0]["lineItem.commodityCode"], "1234.56")
        self.assertEqual(rows[0]["parcelNumbers"], "18309142057")
        self.assertEqual(rows[0]["lineItem.goodsDescription"], "Ordner")
        self.assertEqual(rows[0]["lineItem.valueInInvoiceCurrency"], "20")
        self.assertEqual(rows[0]["invoice.totalGoodsValue.amount"], "20")
        self.assertEqual(rows[0]["totalGrossWeightInKg"], "3")
        self.client.request_product.assert_called_once_with("ART-1")
        self.bridge_product_filter.assert_called_once_with(erp_nr__in={"ART-1"})

    def test_missing_bridge_customs_tariff_number_is_reported(self):
        self.bridge_product_filter.return_value.values_list.return_value = []
        with self.assertRaisesRegex(ValueError, "Bridge fehlt die Zollwarennummer für Artikel: ART-1"):
            SwissCustomsCsvExportService().export_microtech_order("10387", client=self.client)
        self.client.request_product.assert_not_called()

    def test_missing_microtech_order_fails_without_creating_bridge_order(self):
        self.client.poll_dataset_records.return_value = {"records": []}
        self.client.poll_dataset_records.side_effect = None
        with self.assertRaisesRegex(ValueError, "Kein Microtech-Vorgang"):
            SwissCustomsCsvExportService().export_microtech_order("99999", client=self.client)
        self.client.request_vorgang.assert_not_called()

    def test_list_action_has_dialog_and_download_endpoint(self):
        model_admin = OrderAdmin(Order, admin.site)
        action = model_admin.get_unfold_action("export_microtech_customs_csv_list")
        self.assertIn("export_microtech_customs_csv_list", model_admin.actions_list)
        self.assertEqual(action.dialog["form_class"].__name__, "MicrotechCustomsCsvForm")
        self.assertEqual(
            reverse("admin:orders_order_microtech_customs_download"),
            "/admin/orders/order/microtech-customs-download/",
        )

    def test_download_endpoint_returns_csv_without_bridge_order(self):
        request = RequestFactory().get("/admin/orders/order/microtech-customs-download/", {"auftr_nr": "10387"})
        request.user = Mock()
        request.user.has_perm.return_value = True
        model_admin = OrderAdmin(Order, admin.site)
        export = SwissCustomsCsvExport(filename="10387.csv", content="field\nvalue\n", row_count=1)
        with (
            patch("orders.admin.microtech_connection") as connection,
            patch("orders.admin.SwissCustomsCsvExportService.export_microtech_order", return_value=export) as generate,
        ):
            connection.return_value.__enter__.return_value = self.client
            response = model_admin.download_microtech_customs_csv(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("10387.csv", response["Content-Disposition"])
        generate.assert_called_once_with("10387", client=self.client)

    def test_list_dialog_submits_order_number_to_download(self):
        request = RequestFactory().post(
            "/admin/orders/order/export_microtech_customs_csv_list/",
            {"auftr_nr": " 10387 ", "_form_submitted": "1"},
        )
        request.user = Mock()
        request.user.has_perm.return_value = True
        response = OrderAdmin(Order, admin.site).export_microtech_customs_csv_list(request)
        self.assertEqual(
            response["HX-Redirect"],
            "/admin/orders/order/microtech-customs-download/?auftr_nr=10387",
        )
