import csv
import io
from decimal import Decimal

from django.test import TestCase

from customer.models import Address, Customer
from orders.models import Order, OrderDetail
from orders.services import SwissCustomsCsvExportService
from products.models import Product


class SwissCustomsCsvExportServiceTest(TestCase):
    def test_export_uses_mapping_defaults_and_current_project_fields(self):
        customer = Customer.objects.create(
            erp_nr="1000",
            email="kunde@example.com",
            vat_id="CHE-123.456.789",
            name="ACME GmbH",
        )
        shipping = Address.objects.create(
            customer=customer,
            name1="ACME GmbH",
            name2="ACME GmbH",
            street="Musterstrasse 7a",
            postal_code="8000",
            city="Zuerich",
            country_code="CH",
            email="versand@example.com",
            first_name="Max",
            last_name="Mustermann",
            phone="+49 8641 975911",
            is_shipping=True,
        )
        billing = Address.objects.create(
            customer=customer,
            name1="ACME GmbH",
            name2="ACME GmbH",
            street="Rechnungsweg 3",
            postal_code="8001",
            city="Zuerich",
            country_code="CH",
            email="rechnung@example.com",
            first_name="Max",
            last_name="Mustermann",
            is_invoice=True,
        )
        order = Order.objects.create(
            api_id="order-1",
            order_number="SW-10001",
            erp_order_id="",
            total_price=Decimal("23.00"),
            shipping_costs=Decimal("3.00"),
            customer=customer,
            billing_address=billing,
            shipping_address=shipping,
        )
        OrderDetail.objects.create(
            order=order,
            erp_nr="ART-1",
            name="Exportartikel",
            unit="",
            quantity=2,
            unit_price=Decimal("10.00"),
            total_price=Decimal("20.00"),
        )
        Product.objects.create(
            erp_nr="ART-1",
            name="Exportartikel Produkt",
            unit="Stk",
            customs_tariff_number="1234.56",
            weight_gross=Decimal("1.5000"),
            weight_net=Decimal("1.2000"),
        )

        export = SwissCustomsCsvExportService().export_order(order)

        self.assertEqual(export.filename, "SW-10001_Max_Mustermann.csv")
        rows = list(csv.DictReader(io.StringIO(export.content)))
        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertEqual(row["customerReference"], "1000")
        self.assertEqual(row["invoice.invoiceNumber"], "SW-10001")
        self.assertEqual(row["importer.address.name1"], "ACME GmbH")
        self.assertEqual(row["importer.address.name2"], "Max Mustermann")
        self.assertEqual(row["importer.address.street1"], "Musterstrasse")
        self.assertEqual(row["importer.address.houseNumber"], "7a")
        self.assertEqual(row["importer.contactPerson.emailAddress"], "versand@example.com")
        self.assertEqual(row["importer.contactPerson.phoneCountryPrefix"], "+49")
        self.assertEqual(row["lineItem.quantity.unit"], "Stk")
        self.assertEqual(row["lineItem.commodityCode"], "1234.56")
        self.assertEqual(row["lineItem.valueInInvoiceCurrency"], "20")
        self.assertEqual(row["invoice.totalGoodsValue.amount"], "20")
        self.assertEqual(row["lineItem.grossWeightInKg"], "3")
        self.assertEqual(row["lineItem.netWeightInKg"], "2.4")
        self.assertEqual(row["totalGrossWeightInKg"], "3")
