from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from django.utils.html import strip_tags
from django.utils.text import get_valid_filename
from loguru import logger

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
    title = _to_str(address.title)
    lowered = name1.lower()

    if not name1:
        return False
    if title and name1.casefold() == title.casefold():
        return False
    if lowered in _SALUTATION_VALUES:
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
    order: Any
    customer: Any
    shipping_address: Any
    billing_address: Any
    details: list[Any]
    product_map: dict[str, Any]


class SwissCustomsCsvExportService(BaseService):
    model = Order

    def export_order(self, order: Order) -> SwissCustomsCsvExport:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        return self._export_context(self._build_context(order))

    def export_microtech_order(self, order_number: str, *, client: Any) -> SwissCustomsCsvExport:
        """Export a Microtech document without creating a Bridge order."""
        from orders.services.order_upsert_microtech import OrderUpsertMicrotechService

        order_number = _to_str(order_number)
        if not order_number:
            raise ValueError("Bitte eine Auftragsnummer eingeben.")
        candidate = OrderUpsertMicrotechService.find_vorgang_by_auftr_nr_graphql(
            order_number=order_number, client=client,
        )
        if candidate is None:
            raise ValueError(f"Kein Microtech-Vorgang zur Auftragsnummer {order_number} gefunden.")
        beleg_nr = _to_str(candidate["BelegNr"])
        vorgang = (client.request_vorgang(beleg_nr) or {}).get("vorgang") or {}
        if _to_str(vorgang.get("belegNr")) != beleg_nr:
            raise ValueError("Der Microtech-Vorgang konnte nicht eindeutig gelesen werden.")
        remote_order_number = _to_str(vorgang.get("orderNumber"))
        if remote_order_number and remote_order_number != order_number:
            raise ValueError("Die Auftragsnummer des Microtech-Vorgangs stimmt nicht überein.")

        header = self._read_microtech_header(client=client, beleg_nr=beleg_nr)
        if _to_str(header.get("AuftrNr")) != order_number:
            raise ValueError("Die Auftragsnummer des Microtech-Belegs stimmt nicht überein.")
        shipping_address = self._address_from_microtech_header(header, "Li")
        billing_address = self._address_from_microtech_header(header, "Re")
        if not shipping_address.street or not shipping_address.postal_code or not shipping_address.country_code:
            raise ValueError("Die Lieferanschrift im Microtech-Vorgang ist unvollständig.")
        if not billing_address.street:
            billing_address = shipping_address

        details = [
            SimpleNamespace(
                erp_nr=_to_str(position.get("erpNumber")),
                name=_to_str(position.get("name")),
                unit=_to_str(position.get("unit")),
                quantity=_to_decimal(position.get("quantity")) or Decimal("0"),
                unit_price=_to_decimal(position.get("unitPrice")) or Decimal("0"),
                total_price=(
                    _to_decimal(position.get("totalPrice"))
                    if position.get("totalPrice") not in (None, "")
                    else (
                        (_to_decimal(position.get("unitPrice")) or Decimal("0"))
                        * (_to_decimal(position.get("quantity")) or Decimal("0"))
                    )
                ),
            )
            for position in (vorgang.get("positions") or [])
            if isinstance(position, dict)
            and _to_str(position.get("erpNumber"))
            and _to_str(position.get("erpNumber")).upper() not in {"V", "F"}
            and (_to_decimal(position.get("quantity")) or Decimal("0")) > 0
        ]
        product_map: dict[str, Any] = {}
        for erp_nr in {_to_str(detail.erp_nr) for detail in details}:
            product = (client.request_product(erp_nr) or {}).get("product") or {}
            if product:
                product_map[erp_nr] = SimpleNamespace(
                    name=_to_str(product.get("name")),
                    unit=_to_str(product.get("unit")),
                    customs_tariff_number=_to_str(product.get("customsTariffNumber")),
                    weight_gross=_to_decimal(product.get("weightGrossKg")),
                    weight_net=_to_decimal(product.get("weightNetKg")),
                )

        document_date = self._parse_microtech_date(vorgang.get("date") or header.get("Dat"))
        customer_number = _to_str(header.get("AdrNr")) or _to_str(vorgang.get("erpAddressNumber"))
        context = _ExportContext(
            order=SimpleNamespace(
                order_number=order_number,
                erp_order_id=beleg_nr,
                api_id="",
                pk=None,
                purchase_date=document_date,
                created_at=document_date,
                total_price=_to_decimal(vorgang.get("brutto")) or Decimal("0"),
                shipping_costs=Decimal("0"),
            ),
            customer=SimpleNamespace(
                erp_nr=customer_number,
                email=_to_str(header.get("ReEMail1")) or _to_str(header.get("LiEMail1")),
                vat_id=self._read_microtech_tax_id(client=client, customer_number=customer_number),
            ),
            shipping_address=shipping_address,
            billing_address=billing_address,
            details=details,
            product_map=product_map,
        )
        return self._export_context(context)

    @staticmethod
    def _read_microtech_header(*, client: Any, beleg_nr: str) -> dict[str, Any]:
        fields = ["BelegNr", "AuftrNr", "AdrNr", "Dat", "ReEMail1", "LiEMail1"]
        for prefix in ("Li", "Re"):
            fields.extend(
                f"{prefix}{suffix}" for suffix in (
                    "Na1", "Na2", "Na3", "Str", "PLZ", "Ort", "LandKennz",
                    "Tel", "AspVNa", "AspNNa",
                )
            )
        quoted_beleg_nr = beleg_nr.replace("'", "''")
        result = client.poll_dataset_records(
            {
                "dataset": "Vorgang",
                "indexField": "BelegNr",
                "range": {"fromValues": [beleg_nr], "toValues": [beleg_nr]},
                "filter": f"BelegNr = '{quoted_beleg_nr}'",
                "fields": fields,
                "limit": 2,
            },
            timeout=180,
        )
        records = [
            record for record in (result.get("records") or result.get("vorgaenge") or [])
            if isinstance(record, dict) and _to_str(record.get("BelegNr")) == beleg_nr
        ]
        if len(records) != 1 or result.get("hasMore"):
            raise ValueError(f"Microtech-Beleg {beleg_nr} konnte nicht eindeutig gelesen werden.")
        return records[0]

    @staticmethod
    def _read_microtech_tax_id(*, client: Any, customer_number: str) -> str:
        if not customer_number:
            return ""
        quoted_customer_number = customer_number.replace("'", "''")
        try:
            result = client.poll_dataset_records(
                {
                    "dataset": "Adressen",
                    "indexField": "Nr",
                    "range": {"fromValues": [customer_number], "toValues": [customer_number]},
                    "filter": f"AdrNr = '{quoted_customer_number}'",
                    "fields": ["AdrNr", "UStId"],
                    "limit": 2,
                },
                timeout=180,
            )
        except Exception as exc:
            logger.warning("Microtech tax ID unavailable for customer {}: {}", customer_number, exc)
            return ""
        records = [
            record for record in (result.get("records") or [])
            if isinstance(record, dict) and _to_str(record.get("AdrNr")) == customer_number
        ]
        return _to_str(records[0].get("UStId")) if len(records) == 1 else ""

    @staticmethod
    def _address_from_microtech_header(header: dict[str, Any], prefix: str) -> SimpleNamespace:
        if prefix == "Li" and not _to_str(header.get("LiStr")):
            prefix = "Re"
        name1 = _to_str(header.get(f"{prefix}Na1"))
        name2 = _to_str(header.get(f"{prefix}Na2"))
        name3 = _to_str(header.get(f"{prefix}Na3"))
        first_name = _to_str(header.get(f"{prefix}AspVNa"))
        last_name = _to_str(header.get(f"{prefix}AspNNa"))
        if name1.casefold() in _SALUTATION_VALUES and not first_name:
            first_name, last_name = name2, name3
        return SimpleNamespace(
            name1=name1,
            name2=name2,
            first_name=first_name,
            last_name=last_name,
            title=name1 if name1.casefold() in _SALUTATION_VALUES else "",
            street=_to_str(header.get(f"{prefix}Str")),
            postal_code=_to_str(header.get(f"{prefix}PLZ")),
            city=_to_str(header.get(f"{prefix}Ort")),
            country_code=_to_str(header.get(f"{prefix}LandKennz")).upper(),
            email=_to_str(header.get(f"{prefix}EMail1")),
            phone=_to_str(header.get(f"{prefix}Tel")),
        )

    @staticmethod
    def _parse_microtech_date(value: object) -> date | str:
        if isinstance(value, (date, datetime)):
            return value
        raw = _to_str(value)
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return raw

    def _export_context(self, context: _ExportContext) -> SwissCustomsCsvExport:

        mappings = list(
            MicrotechSwissCustomsFieldMapping.objects
            .filter(is_active=True)
            .order_by("priority", "portal_field", "id")
        )
        if not mappings:
            raise ValueError("Kein aktives Schweiz-Zoll-Feldmapping konfiguriert.")

        if not context.details:
            raise ValueError("Der Vorgang hat keine Artikelpositionen fuer den CSV-Export.")

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
            return strip_tags(mapping.static_value or "").strip()
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
