from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils.text import get_valid_filename

from core.services import BaseService
from customer.models import Address, Customer
from microtech.models import MicrotechSwissCustomsFieldMapping
from orders.models import Order, OrderDetail
from products.models import Product


_BOOL_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off", "nein"}
_SALUTATION_VALUES = {"herr", "frau", "mr", "mrs", "ms", "miss", "mister", "madam", "madame"}
_HOUSE_NUMBER_RE = re.compile(r"^(?P<street>.+?)\s+(?P<number>\d+[a-zA-Z]?(?:[/-]\d+[a-zA-Z]?)?)$")
_PHONE_PREFIX_RE = re.compile(r"^(?P<prefix>\+?\d{1,4})[\s/.-]+(?P<number>.+)$")


def _to_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def _normalize_decimal(value: object) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return ""
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _resolve_attr_path(obj: object | None, path: str) -> object:
    current = obj
    for segment in [part for part in path.split(".") if part]:
        if current is None:
            return ""
        current = getattr(current, segment, "")
    return current


def _split_phone(value: str) -> tuple[str, str]:
    phone = _to_str(value)
    if not phone:
        return "", ""
    normalized = phone.replace("(0)", "").strip()
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    match = _PHONE_PREFIX_RE.match(normalized)
    if not match:
        return "", normalized
    return _to_str(match.group("prefix")), _to_str(match.group("number"))


def _split_street_and_house_number(value: str) -> tuple[str, str]:
    street = _to_str(value)
    if not street:
        return "", ""
    match = _HOUSE_NUMBER_RE.match(street)
    if not match:
        return street, ""
    return _to_str(match.group("street")), _to_str(match.group("number"))


def _address_looks_like_company(address: Address | None) -> bool:
    if address is None:
        return False
    name1 = _to_str(address.name1)
    name2 = _to_str(address.name2)
    first_name = _to_str(address.first_name)
    last_name = _to_str(address.last_name)
    lowered = name1.lower()

    if not name1:
        return False
    if lowered in _SALUTATION_VALUES:
        return False
    if name2 and name1 == name2:
        return True
    if first_name or last_name:
        return False
    return True


def _full_name(address: Address | None) -> str:
    if address is None:
        return ""
    full_name = f"{_to_str(address.first_name)} {_to_str(address.last_name)}".strip()
    if full_name:
        return full_name
    name2 = _to_str(address.name2)
    if name2 and name2 != _to_str(address.name1):
        return name2
    return _to_str(address.name1)


@dataclass(slots=True)
class SwissCustomsCsvExport:
    filename: str
    content: str
    row_count: int


@dataclass(slots=True)
class _ExportContext:
    order: Order
    customer: Customer | None
    shipping_address: Address | None
    billing_address: Address | None
    details: list[OrderDetail]
    product_map: dict[str, Product]


class SwissCustomsCsvExportService(BaseService):
    model = Order

    def export_order(self, order: Order) -> SwissCustomsCsvExport:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        mappings = list(
            MicrotechSwissCustomsFieldMapping.objects
            .filter(is_active=True)
            .order_by("priority", "portal_field", "id")
        )
        if not mappings:
            raise ValueError("Kein aktives Schweiz-Zoll-Feldmapping konfiguriert.")

        context = self._build_context(order)
        if not context.details:
            raise ValueError("Die Bestellung hat keine Bestellpositionen fuer den CSV-Export.")

        fieldnames = [mapping.portal_field for mapping in mappings]
        rows = [self._build_row(mapping_list=mappings, context=context, detail=detail) for detail in context.details]

        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

        return SwissCustomsCsvExport(
            filename=self._build_filename(context),
            content=stream.getvalue(),
            row_count=len(rows),
        )

    @staticmethod
    def _build_context(order: Order) -> _ExportContext:
        customer = order.customer
        shipping_address = order.shipping_address or getattr(customer, "shipping_address", None)
        billing_address = order.billing_address or getattr(customer, "billing_address", None) or shipping_address
        details = list(order.details.all().order_by("id"))

        erp_nrs = {_to_str(detail.erp_nr) for detail in details if _to_str(detail.erp_nr)}
        products = Product.objects.filter(erp_nr__in=erp_nrs) if erp_nrs else Product.objects.none()
        product_map = {product.erp_nr: product for product in products}

        return _ExportContext(
            order=order,
            customer=customer,
            shipping_address=shipping_address,
            billing_address=billing_address,
            details=details,
            product_map=product_map,
        )

    def _build_row(
        self,
        *,
        mapping_list: list[MicrotechSwissCustomsFieldMapping],
        context: _ExportContext,
        detail: OrderDetail,
    ) -> dict[str, str]:
        row: dict[str, str] = {}
        product = context.product_map.get(_to_str(detail.erp_nr))
        for mapping in mapping_list:
            raw_value = self._resolve_mapping_value(
                mapping=mapping,
                context=context,
                detail=detail,
                product=product,
            )
            row[mapping.portal_field] = self._format_value(raw_value, value_kind=mapping.value_kind)
        return row

    def _resolve_mapping_value(
        self,
        *,
        mapping: MicrotechSwissCustomsFieldMapping,
        context: _ExportContext,
        detail: OrderDetail,
        product: Product | None,
    ) -> object:
        source_type = mapping.source_type
        source_path = _to_str(mapping.source_path)

        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.STATIC:
            return mapping.static_value
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.ORDER:
            return _resolve_attr_path(context.order, source_path)
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.CUSTOMER:
            return _resolve_attr_path(context.customer, source_path)
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.BILLING_ADDRESS:
            return _resolve_attr_path(context.billing_address, source_path)
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.SHIPPING_ADDRESS:
            return _resolve_attr_path(context.shipping_address, source_path)
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.ORDER_DETAIL:
            return _resolve_attr_path(detail, source_path)
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.PRODUCT:
            return _resolve_attr_path(product, source_path)
        if source_type == MicrotechSwissCustomsFieldMapping.SourceType.COMPUTED:
            return self._resolve_computed_value(
                key=source_path,
                context=context,
                detail=detail,
                product=product,
            )
        raise ValueError(f"Unsupported source_type '{source_type}' for mapping '{mapping.portal_field}'.")

    def _resolve_computed_value(
        self,
        *,
        key: str,
        context: _ExportContext,
        detail: OrderDetail,
        product: Product | None,
    ) -> object:
        shipping_address = context.shipping_address
        customer = context.customer

        if key == "shipping_name1":
            if _address_looks_like_company(shipping_address):
                return _to_str(getattr(shipping_address, "name1", "")) or _to_str(getattr(shipping_address, "name2", ""))
            return _full_name(shipping_address)

        if key == "shipping_name2":
            if not _address_looks_like_company(shipping_address):
                return ""
            contact_name = _full_name(shipping_address)
            company_name = _to_str(getattr(shipping_address, "name1", ""))
            if not contact_name or contact_name == company_name:
                return ""
            return contact_name

        if key == "shipping_contact_name":
            return _full_name(shipping_address)

        if key == "shipping_email_or_customer_email":
            return _to_str(getattr(shipping_address, "email", "")) or _to_str(getattr(customer, "email", ""))

        if key == "shipping_phone_country_prefix":
            prefix, _number = _split_phone(_to_str(getattr(shipping_address, "phone", "")))
            return prefix

        if key == "shipping_phone_number":
            _prefix, number = _split_phone(_to_str(getattr(shipping_address, "phone", "")))
            return number

        if key == "shipping_house_number":
            _street, house_number = _split_street_and_house_number(_to_str(getattr(shipping_address, "street", "")))
            return house_number

        if key == "shipping_street_name":
            street_name, _house_number = _split_street_and_house_number(_to_str(getattr(shipping_address, "street", "")))
            return street_name

        if key == "shipping_is_company":
            return _address_looks_like_company(shipping_address)

        if key == "invoice_number":
            return _to_str(context.order.erp_order_id) or _to_str(context.order.order_number) or _to_str(context.order.api_id)

        if key == "invoice_date_dd_mm_yyyy":
            return context.order.purchase_date or context.order.created_at

        if key == "invoice_total_goods_value":
            if context.details:
                total = Decimal("0.00")
                for row in context.details:
                    row_total = row.total_price
                    if row_total is None:
                        row_total = (row.unit_price or Decimal("0.00")) * Decimal(row.quantity or 0)
                    total += row_total or Decimal("0.00")
                return total
            order_total = context.order.total_price or Decimal("0.00")
            shipping_costs = context.order.shipping_costs or Decimal("0.00")
            result = order_total - shipping_costs
            return result if result > 0 else order_total

        if key == "order_detail_or_product_name":
            return _to_str(detail.name) or _to_str(getattr(product, "name", "")) or _to_str(detail.erp_nr)

        if key == "order_detail_or_product_unit":
            return _to_str(detail.unit) or _to_str(getattr(product, "unit", ""))

        if key == "line_item_gross_weight_kg":
            return self._line_item_weight(detail=detail, product=product, field_name="weight_gross")

        if key == "line_item_net_weight_kg":
            return self._line_item_weight(detail=detail, product=product, field_name="weight_net")

        if key == "order_total_gross_weight_kg":
            total = Decimal("0.00")
            has_any_weight = False
            for row in context.details:
                row_product = context.product_map.get(_to_str(row.erp_nr))
                weight = self._line_item_weight(detail=row, product=row_product, field_name="weight_gross")
                decimal_weight = _to_decimal(weight)
                if decimal_weight is None:
                    continue
                has_any_weight = True
                total += decimal_weight
            return total if has_any_weight else ""

        raise ValueError(f"Unknown computed mapping resolver '{key}'.")

    @staticmethod
    def _line_item_weight(*, detail: OrderDetail, product: Product | None, field_name: str) -> Decimal | str:
        weight = _to_decimal(getattr(product, field_name, None))
        if weight is None:
            return ""
        quantity = Decimal(detail.quantity or 0)
        return weight * quantity

    @staticmethod
    def _format_value(value: object, *, value_kind: str) -> str:
        if value in (None, ""):
            return ""

        normalized_kind = _to_str(value_kind).lower() or "text"
        if normalized_kind == "bool":
            if isinstance(value, bool):
                return "true" if value else "false"
            normalized = _to_str(value).lower()
            if normalized in _BOOL_TRUE_VALUES:
                return "true"
            if normalized in _BOOL_FALSE_VALUES:
                return "false"
            return normalized

        if normalized_kind == "decimal":
            return _normalize_decimal(value)

        if normalized_kind == "int":
            try:
                return str(int(Decimal(str(value).replace(",", "."))))
            except (ArithmeticError, InvalidOperation, ValueError):
                return _to_str(value)

        if normalized_kind == "date":
            if isinstance(value, datetime):
                return value.strftime("%d.%m.%Y")
            if isinstance(value, date):
                return value.strftime("%d.%m.%Y")
            return _to_str(value)

        return _to_str(value)

    @staticmethod
    def _build_filename(context: _ExportContext) -> str:
        order_number = _to_str(context.order.order_number) or _to_str(context.order.erp_order_id) or f"order-{context.order.pk}"
        recipient = _full_name(context.shipping_address) or _to_str(getattr(context.shipping_address, "name1", "")) or "customs"
        return get_valid_filename(f"{order_number} {recipient}.csv")
