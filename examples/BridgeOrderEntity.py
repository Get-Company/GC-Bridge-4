from sqlalchemy import and_

from main import db
from datetime import datetime
from loguru import logger
import csv
from main.src.Entity.Bridge.Customer.BridgeCustomerEntity import BridgeCustomerEntity
from main.src.Entity.Bridge.Orders.BridgeOrderStateEntity import BridgeOrderStateEntity

import xml.etree.ElementTree as ET
# Many-To-Many for Order/Product
order_product = db.Table('bridge_order_product_entity',
                         db.Column('id', db.Integer(), primary_key=True, nullable=False),
                         db.Column('order_id', db.Integer, db.ForeignKey('bridge_order_entity.id')),
                         db.Column('product_id', db.Integer, db.ForeignKey('bridge_product_entity.id')),
                         db.Column('quantity', db.Integer()),
                         db.Column('unit_price', db.Float()),
                         db.Column('total_price', db.Float())
                         )


# Order Entity
class BridgeOrderEntity(db.Model):
    __tablename__ = "bridge_order_entity"

    id = db.Column(db.Integer(), primary_key=True, nullable=False, autoincrement=True)
    api_id = db.Column(db.CHAR(36), nullable=False)
    erp_order_id = db.Column(db.String(255), nullable=True)
    purchase_date = db.Column(db.DateTime(), nullable=False)
    description = db.Column(db.String(4096), nullable=True)
    total_price = db.Column(db.Float(), nullable=False)
    shipping_costs = db.Column(db.Float(), nullable=False)
    payment_method = db.Column(db.String(255), nullable=True)
    shipping_method = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(), nullable=True, default=datetime.now())
    edited_at = db.Column(db.DateTime(), nullable=False)
    order_number = db.Column(db.String(255), nullable=True)

    """
    Relations
    """
    # Relation one - to - one
    order_state = db.relationship("BridgeOrderStateEntity", uselist=False, back_populates="order")

    # Relation many - to - one
    customer = db.relationship(
        "BridgeCustomerEntity",
        uselist=False,
        back_populates="orders")

    customer_id = db.Column(db.Integer(), db.ForeignKey('bridge_customer_entity.id'))

    # Order Products Relation many - to - many
    products = db.relationship(
        'BridgeProductEntity',
        secondary=order_product,
        back_populates='orders',
        lazy='joined')

    def update_entity(self, entity):
        """
        The entity is produced by ERP. Simply use the same names
        self.hans = entity.hans
        """
        self.id = entity.id
        self.api_id = entity.api_id
        self.description = entity.description
        self.edited_at = datetime.now()

        return self

    def get_order_products(self):
        """
        Returns a list of dictionaries containing product information (id, quantity, unit_price, total_price)
        for all products associated with this order.
        """
        order_products = db.session.query(
            order_product.c.product_id,
            order_product.c.quantity,
            order_product.c.unit_price,
            order_product.c.total_price
        ).filter(
            order_product.c.order_id == self.id
        ).all()

        product_list = []
        for product in order_products:
            product_list.append({
                'product_id': product[0],
                'quantity': product[1],
                'unit_price': product[2],
                'total_price': product[3]
            })

        return product_list

    def add_order_product_fields_to_product(self):
        for product in self.products:
            order_product_found = db.session.query(
                order_product.c.quantity,
                order_product.c.unit_price,
                order_product.c.total_price
            ).filter(
                and_(
                    order_product.c.product_id == product.id,
                    order_product.c.order_id == self.id
                )
            ).one_or_none()

            product.quantity = order_product_found.quantity
            product.unit_price = order_product_found.unit_price
            product.total_price = order_product_found.total_price

        return True

    def get_open_orders(self):
        """
        Query the database to get all orders with payment_state, shipping_state, and order_state equal to 0 (new orders).
        :return: A list of BridgeOrderEntity objects.
        """
        try:
            new_orders = BridgeOrderEntity.query.join(BridgeOrderStateEntity).filter(
                BridgeOrderStateEntity.payment_state == 0,
                BridgeOrderStateEntity.shipping_state == 0,
                BridgeOrderStateEntity.order_state == 0
            ).all()

            self.new_orders = new_orders
        except Exception as e:
            print(f"Error querying new orders: {str(e)}")

    def map_sw5_to_db(self, order):
        self.api_id = order["id"]
        self.purchase_date = datetime.strptime(order["orderTime"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
        self.total_price = order["invoiceAmountNet"]
        self.shipping_costs = order["invoiceShippingNet"]
        self.payment_method = order["payment"]["description"]
        self.created_at = datetime.now()
        self.edited_at = datetime.now()
        self.erp_order_id = "SW5_" + str(order["id"])
        self.order_number = order["number"]
        self.shipping_method = order["billing"]["country"]["iso"]
        self.description = order["customerComment"]

        return self

    def map_bridge_to_gls_csv(self):
        """ This export needs to be called """
        field_names = [
            "customerReference",
            "parcelNumbers",
            "isExportDeclarationRequested",
            "exportDeclarationNumbers",
            "transitMRNs",
            "transitType",
            "glsIncotermCode",
            "totalGrossWeightInKg",
            "exporter.address.name1",
            "exporter.address.name2",
            "exporter.address.street1",
            "exporter.address.street2",
            "exporter.address.houseNumber",
            "exporter.address.postcode",
            "exporter.address.city1",
            "exporter.address.stateOrRegion",
            "exporter.address.countryCode",
            "exporter.contactPerson.name",
            "exporter.contactPerson.emailAddress",
            "exporter.contactPerson.phoneCountryPrefix",
            "exporter.contactPerson.phoneNumber",
            "exporter.contactPerson.mobileCountryPrefix",
            "exporter.contactPerson.mobileNumber",
            "exporter.eoriNumber",
            "exporter.swissUid",
            "exporter.taxId",
            "exporter.vatRegistrationNumber",
            "exporter.isCommercial",
            "exporter.authorizationNumber",
            "exporter.loadingPlaceCode",
            "importer.address.name1",
            "importer.address.name2",
            "importer.address.street1",
            "importer.address.street2",
            "importer.address.houseNumber",
            "importer.address.postcode",
            "importer.address.city1",
            "importer.address.stateOrRegion",
            "importer.address.countryCode",
            "importer.contactPerson.name",
            "importer.contactPerson.emailAddress",
            "importer.contactPerson.phoneCountryPrefix",
            "importer.contactPerson.phoneNumber",
            "importer.contactPerson.mobileCountryPrefix",
            "importer.contactPerson.mobileNumber",
            "importer.eoriNumber",
            "importer.taxId",
            "importer.isCommercial",
            "consignee.address.name1",
            "consignee.address.name2",
            "consignee.address.street1",
            "consignee.address.street2",
            "consignee.address.houseNumber",
            "consignee.address.postcode",
            "consignee.address.city1",
            "consignee.address.stateOrRegion",
            "consignee.address.countryCode",
            "consignee.contactPerson.name",
            "consignee.contactPerson.emailAddress",
            "consignee.contactPerson.phoneCountryPrefix",
            "consignee.contactPerson.phoneNumber",
            "consignee.contactPerson.mobileCountryPrefix",
            "consignee.contactPerson.mobileNumber",
            "invoice.invoiceNumber",
            "invoice.invoiceDate",
            "invoice.totalGoodsValue.amount",
            "invoice.totalGoodsValue.currency",
            "lineItem.quantity.amount",
            "lineItem.quantity.unit",
            "lineItem.commodityCode",
            "lineItem.goodsDescription",
            "lineItem.countryOfOrigin",
            "lineItem.valueInInvoiceCurrency",
            "lineItem.preferentialTrade.isEligibleForPreference",
            "lineItem.preferentialTrade.proofOfPreference.type",
            "lineItem.preferentialTrade.proofOfPreference.referenceNumber",
            "lineItem.statisticalValue.amount",
            "lineItem.statisticalValue.currency",
            "lineItem.statisticalQuantity",
            "lineItem.nationalCustomsFieldsDE.regionOfOrigin",
            "lineItem.nationalCustomsFieldsBE.regionOfOrigin",
            "lineItem.grossWeightInKg",
            "lineItem.netWeightInKg"
        ]
        self.add_order_product_fields_to_product()

        # Get the shipping address
        shipping_address = self.customer.get_default_shipping_address()

        rows = []
        invoice_total_dummy = len(self.products)
        invoice_lineitem_dummy = 1

        weight_total_dummy = len(self.products)
        weight_lineitem_dummy = 1

        for i, product in enumerate(self.products):
            row = {
                "customerReference": self.customer.erp_nr,
                "parcelNumbers": "18309142057",
                "isExportDeclarationRequested": False,
                "exportDeclarationNumbers": "",
                "transitMRNs": "",
                "transitType": "",
                "glsIncotermCode": 10,
                "totalGrossWeightInKg": weight_total_dummy,
                # Sender
                "exporter.address.name1": "Egon Heimann GmbH Classei",
                "exporter.address.name2": "",
                "exporter.address.street1": "Staudacherstr.",
                "exporter.address.street2": "",
                "exporter.address.houseNumber": "7e",
                "exporter.address.postcode": "83250",
                "exporter.address.city1": "Marquartstein",
                "exporter.address.stateOrRegion": "",
                "exporter.address.countryCode": "DE",
                "exporter.contactPerson.name": "Rita Angermeier",
                "exporter.contactPerson.emailAddress": "rangermeier@classei.de",
                "exporter.contactPerson.phoneCountryPrefix": "+49",
                "exporter.contactPerson.phoneNumber": "8641975911",
                "exporter.contactPerson.mobileCountryPrefix": "",
                "exporter.contactPerson.mobileNumber": "",
                "exporter.eoriNumber": "DE4936795",
                "exporter.swissUid": "",
                "exporter.taxId": "DE131554917",
                "exporter.vatRegistrationNumber": "DE131554917",
                "exporter.isCommercial": True,
                "exporter.authorizationNumber": "",
                "exporter.loadingPlaceCode": "",
                # Importer
                "importer.address.name1": shipping_address.na2 if shipping_address.na1 == "Firma" else shipping_address.first_name + " " + shipping_address.last_name,
                "importer.address.name2": shipping_address.first_name + " " + shipping_address.last_name if shipping_address.na1 == "Firma" else "",
                "importer.address.street1": shipping_address.str,
                "importer.address.street2": "",
                "importer.address.houseNumber": "",
                "importer.address.postcode": shipping_address.plz,
                "importer.address.city1": shipping_address.city,
                "importer.address.stateOrRegion": "",
                "importer.address.countryCode": shipping_address.land_ISO2,
                "importer.contactPerson.name": shipping_address.first_name + " " + shipping_address.last_name,
                "importer.contactPerson.emailAddress": self.customer.email,
                "importer.contactPerson.phoneCountryPrefix": "",
                "importer.contactPerson.phoneNumber": "",
                "importer.contactPerson.mobileCountryPrefix": "",
                "importer.contactPerson.mobileNumber": "",
                "importer.eoriNumber": "",
                "importer.taxId": self.customer.ustid if self.customer.ustid else "",
                "importer.isCommercial": True if shipping_address.na1 == "Firma" else False,
                # Receiver
                "consignee.address.name1": shipping_address.na2 if shipping_address.na1 == "Firma" else shipping_address.first_name + " " + shipping_address.last_name,
                "consignee.address.name2": shipping_address.first_name + " " + shipping_address.last_name if shipping_address.na1 == "Firma" else "",
                "consignee.address.street1": shipping_address.str,
                "consignee.address.street2": "",
                "consignee.address.houseNumber": "",
                "consignee.address.postcode": shipping_address.plz,
                "consignee.address.city1": shipping_address.city,
                "consignee.address.stateOrRegion": "",
                "consignee.address.countryCode": shipping_address.land_ISO2,
                "consignee.contactPerson.name": shipping_address.first_name + " " + shipping_address.last_name,
                "consignee.contactPerson.emailAddress": self.customer.email,
                "consignee.contactPerson.phoneCountryPrefix": "",
                "consignee.contactPerson.phoneNumber": "",
                "consignee.contactPerson.mobileCountryPrefix": "",
                "consignee.contactPerson.mobileNumber": "",
                "invoice.invoiceNumber": self.erp_order_id,
                "invoice.invoiceDate": self.created_at.strftime("%d.%m.%Y"),
                "invoice.totalGoodsValue.amount": invoice_total_dummy,
                "invoice.totalGoodsValue.currency": "EUR",
                "lineItem.quantity.amount": product.quantity,
                "lineItem.quantity.unit": product.unit,
                "lineItem.commodityCode": "",
                "lineItem.goodsDescription": product.name,
                "lineItem.countryOfOrigin": "",
                "lineItem.valueInInvoiceCurrency": invoice_lineitem_dummy,
                "lineItem.preferentialTrade.isEligibleForPreference": False,
                "lineItem.preferentialTrade.proofOfPreference.type": "",
                "lineItem.preferentialTrade.proofOfPreference.referenceNumber": "",
                "lineItem.statisticalValue.amount": invoice_lineitem_dummy,
                "lineItem.statisticalValue.currency": "EUR",
                "lineItem.statisticalQuantity": "",
                "lineItem.nationalCustomsFieldsDE.regionOfOrigin": "",
                "lineItem.nationalCustomsFieldsBE.regionOfOrigin": "",
                "lineItem.grossWeightInKg": weight_lineitem_dummy,
                "lineItem.netWeightInKg": weight_lineitem_dummy
            }
            # On the last item, add + Versandkosten since they have to be added to one item
            if i == len(self.products) - 1:
                row["lineItem.goodsDescription"] += " + Versandkosten"
            rows.append(row)
        path = "main/static/downloads/"
        file = self.order_number + " " + shipping_address.na2 + ".csv"

        with open(path + file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=field_names)
            writer.writeheader()
            writer.writerows(rows)

        return file

    def __repr__(self):
        return f"" \
               f"Order: {self.api_id} " \
               f"from: {self.purchase_date}. " \
               f"Total: {self.total_price}, " \
               f"Shipping:{self.shipping_costs} - Land: {self.shipping_method} " \
               f"ERP Order ID: {self.erp_order_id} - Order Number:{self.order_number} " \
               f"Payment: {self.payment_method}"
