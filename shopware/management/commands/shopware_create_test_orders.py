from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from shopware.services import Shopware6Service

STOREFRONT_TYPE_ID = "8a243080f92e4c719546314b577cf82b"
ORDER_STATE_OPEN_ID = "0d6ea12d37c9481ab29a412f70b06fe5"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_decimal(value: Any, default: Decimal = Decimal("0.00")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return []


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned or "channel"


def _calc_total_and_tax(*, unit_price: Decimal, quantity: int, tax_rate: Decimal) -> tuple[Decimal, Decimal]:
    total = (unit_price * Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax = (total * tax_rate / (Decimal("100") + tax_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total, tax


def _calc_price_obj(*, unit_price: Decimal, quantity: int, tax_rate: Decimal) -> dict[str, Any]:
    total, tax = _calc_total_and_tax(unit_price=unit_price, quantity=quantity, tax_rate=tax_rate)
    return {
        "unitPrice": float(unit_price),
        "quantity": quantity,
        "totalPrice": float(total),
        "calculatedTaxes": [
            {
                "tax": float(tax),
                "taxRate": float(tax_rate),
                "price": float(total),
            }
        ],
        "taxRules": [
            {
                "taxRate": float(tax_rate),
                "percentage": 100,
            }
        ],
        "referencePrice": None,
        "listPrice": None,
        "regulationPrice": None,
    }


def _calc_price_definition(*, unit_price: Decimal, quantity: int, tax_rate: Decimal) -> dict[str, Any]:
    return {
        "price": float(unit_price),
        "taxRules": [
            {
                "taxRate": float(tax_rate),
                "percentage": 100,
            }
        ],
        "quantity": quantity,
        "isCalculated": True,
        "referencePriceDefinition": None,
        "listPrice": None,
        "regulationPrice": None,
        "type": "quantity",
    }


def _line_item_states(product: dict[str, Any]) -> list[str]:
    states = _as_list(product.get("states"))
    return states or ["is-physical"]


@dataclass(slots=True)
class GroupCustomer:
    group_id: str
    group_name: str
    customer: dict[str, Any]

    @property
    def customer_id(self) -> str:
        return str(self.customer.get("id") or "")

    @property
    def customer_number(self) -> str:
        return str(self.customer.get("customerNumber") or "")


class Command(BaseCommand):
    help = (
        "Create test orders in Shopware for each sales channel. "
        "Uses one customer per available customer group (if possible) and writes a detailed log file."
    )

    def add_arguments(self, parser):
        parser.add_argument("--product-a", default="204113", help="Product number for first line item.")
        parser.add_argument("--qty-a", type=int, default=250, help="Quantity for first line item.")
        parser.add_argument("--product-b", default="581000", help="Product number for second line item.")
        parser.add_argument("--qty-b", type=int, default=5, help="Quantity for second line item.")
        parser.add_argument(
            "--sales-channel-id",
            action="append",
            default=[],
            help="Optional: process only these sales channel ids (repeatable).",
        )
        parser.add_argument(
            "--storefront-only",
            action="store_true",
            help="Only include storefront sales channels.",
        )
        parser.add_argument(
            "--log-file",
            default="tmp/logs/shopware_create_test_orders.log",
            help="File path for detailed command log.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build and log payloads without creating orders.",
        )

    @staticmethod
    def _add_file_sink(log_file: str) -> tuple[int, Path]:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        sink_id = logger.add(
            str(path),
            level="DEBUG",
            enqueue=False,
            backtrace=True,
            diagnose=True,
            rotation="10 MB",
            encoding="utf-8",
        )
        return sink_id, path

    def handle(self, *args, **options):
        sink_id, log_path = self._add_file_sink(options["log_file"])
        logger.info("Starting shopware_create_test_orders. log_file={}", log_path)

        try:
            service = Shopware6Service()

            sales_channels = self._load_sales_channels(
                service=service,
                requested_ids=[x.strip() for x in options["sales_channel_id"] if x and x.strip()],
                storefront_only=bool(options["storefront_only"]),
            )
            if not sales_channels:
                raise CommandError("No sales channels found for requested filters.")

            group_customers = self._load_group_customers(service=service)
            if not group_customers:
                raise CommandError("No customers found in any customer group.")

            product_specs = [
                {"product_number": str(options["product_a"]).strip(), "quantity": int(options["qty_a"])},
                {"product_number": str(options["product_b"]).strip(), "quantity": int(options["qty_b"])},
            ]
            products = self._load_products(service=service, specs=product_specs)

            unit_price_map = self._load_unit_prices(
                service=service,
                products=products,
            )

            used_customers: set[str] = set()
            results: list[dict[str, Any]] = []

            for index, channel in enumerate(sales_channels, start=1):
                selected = self._pick_customer_for_channel(
                    channel_name=str(channel.get("name") or ""),
                    candidates=group_customers,
                    used_customer_ids=used_customers,
                )
                if not selected:
                    results.append(
                        {
                            "sales_channel_id": channel.get("id"),
                            "sales_channel_name": channel.get("name"),
                            "status": "error",
                            "error": "No customer candidate available.",
                        }
                    )
                    continue

                used_customers.add(selected.customer_id)
                order_number = self._build_order_number(channel=channel, index=index)
                payload = self._build_order_payload(
                    channel=channel,
                    selected=selected,
                    products=products,
                    product_specs=product_specs,
                    unit_price_map=unit_price_map,
                    order_number=order_number,
                )

                logger.info(
                    "Prepared order payload for channel '{}' with customer '{}' ({}) and order_number '{}'.",
                    channel.get("name"),
                    selected.customer_number,
                    selected.group_name,
                    order_number,
                )

                if options["dry_run"]:
                    results.append(
                        {
                            "sales_channel_id": channel.get("id"),
                            "sales_channel_name": channel.get("name"),
                            "customer_id": selected.customer_id,
                            "customer_number": selected.customer_number,
                            "customer_group": selected.group_name,
                            "order_number": order_number,
                            "status": "dry-run",
                        }
                    )
                    continue

                try:
                    service.client.request_post("/order", payload=payload)
                    created = service.client.request_post(
                        "/search/order",
                        payload={
                            "limit": 1,
                            "filter": [
                                {"type": "equals", "field": "orderNumber", "value": order_number},
                            ],
                            "sort": [{"field": "createdAt", "order": "DESC"}],
                        },
                    )
                    created_row = (created.get("data") or [None])[0]
                    results.append(
                        {
                            "sales_channel_id": channel.get("id"),
                            "sales_channel_name": channel.get("name"),
                            "customer_id": selected.customer_id,
                            "customer_number": selected.customer_number,
                            "customer_group": selected.group_name,
                            "order_number": order_number,
                            "order_id": (created_row or {}).get("id"),
                            "status": "created",
                        }
                    )
                    logger.success(
                        "Created order '{}' (id={}) for channel '{}' with customer '{}'.",
                        order_number,
                        (created_row or {}).get("id"),
                        channel.get("name"),
                        selected.customer_number,
                    )
                except Exception as exc:
                    error_text = str(exc)
                    logger.exception(
                        "Failed to create order '{}' for channel '{}' with customer '{}'.",
                        order_number,
                        channel.get("name"),
                        selected.customer_number,
                    )
                    results.append(
                        {
                            "sales_channel_id": channel.get("id"),
                            "sales_channel_name": channel.get("name"),
                            "customer_id": selected.customer_id,
                            "customer_number": selected.customer_number,
                            "customer_group": selected.group_name,
                            "order_number": order_number,
                            "status": "error",
                            "error": error_text[:1000],
                        }
                    )

            summary = {
                "sales_channels_total": len(sales_channels),
                "customers_available": len(group_customers),
                "orders_created": len([r for r in results if r.get("status") == "created"]),
                "orders_failed": len([r for r in results if r.get("status") == "error"]),
                "dry_run": bool(options["dry_run"]),
                "log_file": str(log_path),
                "results": results,
            }
            logger.info("{}", json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
            self.stdout.write(json.dumps(summary, ensure_ascii=True))
        finally:
            logger.info("Finished shopware_create_test_orders. log_file={}", log_path)
            logger.remove(sink_id)

    def _load_sales_channels(
        self,
        *,
        service: Shopware6Service,
        requested_ids: list[str],
        storefront_only: bool,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        if requested_ids:
            filters.append(
                {
                    "type": "equalsAny",
                    "field": "id",
                    "value": "|".join(requested_ids),
                }
            )
        if storefront_only:
            filters.append(
                {
                    "type": "equals",
                    "field": "typeId",
                    "value": STOREFRONT_TYPE_ID,
                }
            )

        payload: dict[str, Any] = {
            "limit": 200,
            "sort": [{"field": "name", "order": "ASC"}],
        }
        if filters:
            payload["filter"] = filters

        response = service.client.request_post("/search/sales-channel", payload=payload)
        return response.get("data") or []

    def _load_group_customers(self, *, service: Shopware6Service) -> list[GroupCustomer]:
        groups_response = service.client.request_post(
            "/search/customer-group",
            payload={
                "limit": 200,
                "sort": [{"field": "name", "order": "ASC"}],
            },
        )
        groups = groups_response.get("data") or []
        result: list[GroupCustomer] = []

        for group in groups:
            group_id = str(group.get("id") or "")
            group_name = str(group.get("name") or "").strip()
            if not group_id:
                continue

            customer_response = service.client.request_post(
                "/search/customer",
                payload={
                    "limit": 1,
                    "filter": [
                        {"type": "equals", "field": "groupId", "value": group_id},
                    ],
                    "sort": [{"field": "createdAt", "order": "DESC"}],
                    "associations": {
                        "defaultBillingAddress": {},
                        "defaultShippingAddress": {},
                    },
                },
            )
            customer = (customer_response.get("data") or [None])[0]
            if not customer:
                continue

            if not (customer.get("defaultBillingAddress") or customer.get("defaultShippingAddress")):
                continue

            result.append(GroupCustomer(group_id=group_id, group_name=group_name, customer=customer))

        logger.info("Loaded {} customer groups with at least one usable customer.", len(result))
        return result

    def _load_products(
        self,
        *,
        service: Shopware6Service,
        specs: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        product_numbers = [str(spec["product_number"]).strip() for spec in specs]
        response = service.client.request_post(
            "/search/product",
            payload={
                "limit": len(product_numbers),
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "productNumber",
                        "value": "|".join(product_numbers),
                    }
                ],
                "associations": {"tax": {}},
            },
        )
        rows = response.get("data") or []
        mapping = {str(row.get("productNumber") or ""): row for row in rows}
        missing = [number for number in product_numbers if number not in mapping]
        if missing:
            raise CommandError(f"Products not found in Shopware: {', '.join(missing)}")
        return mapping

    def _load_unit_prices(
        self,
        *,
        service: Shopware6Service,
        products: dict[str, dict[str, Any]],
    ) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for product_number, product in products.items():
            product_id = str(product.get("id") or "")
            unit_price = Decimal("0.00")

            if product_id:
                recent = service.client.request_post(
                    "/search/order-line-item",
                    payload={
                        "limit": 1,
                        "filter": [
                            {"type": "equals", "field": "productId", "value": product_id},
                            {"type": "equals", "field": "type", "value": "product"},
                        ],
                        "sort": [{"field": "createdAt", "order": "DESC"}],
                    },
                )
                recent_row = (recent.get("data") or [None])[0]
                if recent_row:
                    unit_price = _to_decimal((recent_row.get("price") or {}).get("unitPrice"))

            if unit_price <= Decimal("0.00"):
                unit_price = _to_decimal((_as_list(product.get("price")) or [{}])[0].get("gross"))

            if unit_price <= Decimal("0.00"):
                raise CommandError(f"Could not resolve unit price for product {product_number}.")

            result[product_number] = unit_price
            logger.info("Unit price for {} resolved as {}", product_number, unit_price)

        return result

    def _pick_customer_for_channel(
        self,
        *,
        channel_name: str,
        candidates: list[GroupCustomer],
        used_customer_ids: set[str],
    ) -> GroupCustomer | None:
        channel_upper = channel_name.upper()

        def target_keywords() -> list[str]:
            if " CH" in f" {channel_upper}" or channel_upper.endswith("CH") or "SCHWEIZ" in channel_upper:
                return ["SCHWEIZ"]
            if " IT" in f" {channel_upper}" or channel_upper.endswith("IT") or "ITAL" in channel_upper:
                return ["ITALIEN"]
            if "B2C" in channel_upper:
                return ["PRIVAT", "B2C"]
            if "DANVIS" in channel_upper:
                return ["SHOPKUNDEN"]
            return ["FIRMA B2B", "B2B"]

        keywords = target_keywords()
        prefer_gc_prefix = "GC |" in channel_name

        def score(item: GroupCustomer) -> tuple[int, int, str]:
            group_upper = item.group_name.upper()
            keyword_hits = sum(1 for keyword in keywords if keyword in group_upper)
            prefix_hit = 1 if (prefer_gc_prefix and item.group_name.startswith("GC |")) else 0
            unused_bonus = 1 if item.customer_id not in used_customer_ids else 0
            return (keyword_hits, prefix_hit + unused_bonus, item.group_name)

        sorted_candidates = sorted(candidates, key=score, reverse=True)
        for item in sorted_candidates:
            if item.customer_id not in used_customer_ids:
                return item
        return sorted_candidates[0] if sorted_candidates else None

    def _build_order_number(self, *, channel: dict[str, Any], index: int) -> str:
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        channel_slug = _slug(str(channel.get("name") or "channel"))[:18]
        return f"TST-{channel_slug}-{index:02d}-{suffix}"

    def _build_order_payload(
        self,
        *,
        channel: dict[str, Any],
        selected: GroupCustomer,
        products: dict[str, dict[str, Any]],
        product_specs: list[dict[str, Any]],
        unit_price_map: dict[str, Decimal],
        order_number: str,
    ) -> dict[str, Any]:
        customer = selected.customer
        address = customer.get("defaultBillingAddress") or customer.get("defaultShippingAddress")
        if not address:
            raise CommandError(
                f"Customer {selected.customer_number} has no default billing/shipping address."
            )

        order_id = uuid4().hex
        order_address_id = uuid4().hex
        order_customer_id = uuid4().hex
        now_iso = _utc_now_iso()

        line_items: list[dict[str, Any]] = []
        order_total = Decimal("0.00")
        order_tax_total = Decimal("0.00")

        for position, spec in enumerate(product_specs, start=1):
            product_number = str(spec["product_number"]).strip()
            quantity = int(spec["quantity"])
            product = products[product_number]
            product_id = str(product.get("id") or "")
            label = str(product.get("name") or product_number)
            tax_rate = _to_decimal((product.get("tax") or {}).get("taxRate"), default=Decimal("19"))
            unit_price = unit_price_map[product_number]

            line_price = _calc_price_obj(unit_price=unit_price, quantity=quantity, tax_rate=tax_rate)
            line_price_def = _calc_price_definition(unit_price=unit_price, quantity=quantity, tax_rate=tax_rate)
            line_total, line_tax = _calc_total_and_tax(
                unit_price=unit_price,
                quantity=quantity,
                tax_rate=tax_rate,
            )
            order_total += line_total
            order_tax_total += line_tax

            line_items.append(
                {
                    "id": uuid4().hex,
                    "identifier": product_id,
                    "type": "product",
                    "referencedId": product_id,
                    "productId": product_id,
                    "quantity": quantity,
                    "label": label,
                    "position": position,
                    "good": True,
                    "removable": True,
                    "stackable": True,
                    "states": _line_item_states(product),
                    "children": [],
                    "price": line_price,
                    "priceDefinition": line_price_def,
                    "payload": {"productNumber": product_number},
                    "createdAt": now_iso,
                }
            )

        net_total = (order_total - order_tax_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if order_total > Decimal("0.00"):
            weighted_tax_rate = (order_tax_total / net_total * Decimal("100")) if net_total > 0 else Decimal("19")
            weighted_tax_rate = weighted_tax_rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            weighted_tax_rate = Decimal("19.00")

        price_obj = {
            "netPrice": float(net_total),
            "totalPrice": float(order_total),
            "positionPrice": float(order_total),
            "rawTotal": float(order_total),
            "calculatedTaxes": [
                {
                    "tax": float(order_tax_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "taxRate": float(weighted_tax_rate),
                    "price": float(order_total),
                }
            ],
            "taxRules": [
                {
                    "taxRate": float(weighted_tax_rate),
                    "percentage": 100,
                }
            ],
            "taxStatus": "gross",
        }

        shipping_costs = {
            "unitPrice": 0.0,
            "quantity": 1,
            "totalPrice": 0.0,
            "calculatedTaxes": [],
            "taxRules": [],
            "referencePrice": None,
            "listPrice": None,
            "regulationPrice": None,
        }

        return {
            "id": order_id,
            "orderNumber": order_number,
            "salesChannelId": str(channel.get("id") or ""),
            "currencyId": str(channel.get("currencyId") or ""),
            "languageId": str(channel.get("languageId") or ""),
            "billingAddressId": order_address_id,
            "currencyFactor": 1,
            "stateId": ORDER_STATE_OPEN_ID,
            "itemRounding": {"decimals": 2, "interval": 0.01, "roundForNet": True},
            "totalRounding": {"decimals": 2, "interval": 0.01, "roundForNet": True},
            "orderDateTime": now_iso,
            "createdAt": now_iso,
            "price": price_obj,
            "shippingCosts": shipping_costs,
            "addresses": [
                {
                    "id": order_address_id,
                    "countryId": address.get("countryId"),
                    "countryStateId": address.get("countryStateId"),
                    "salutationId": address.get("salutationId") or customer.get("salutationId"),
                    "firstName": address.get("firstName") or customer.get("firstName") or "Test",
                    "lastName": address.get("lastName") or customer.get("lastName") or "User",
                    "street": address.get("street") or "Teststr. 1",
                    "zipcode": address.get("zipcode") or "00000",
                    "city": address.get("city") or "Teststadt",
                    "company": address.get("company") or customer.get("company"),
                    "department": address.get("department"),
                    "title": address.get("title") or customer.get("title"),
                    "phoneNumber": address.get("phoneNumber"),
                    "additionalAddressLine1": address.get("additionalAddressLine1"),
                    "additionalAddressLine2": address.get("additionalAddressLine2"),
                    "vatId": (_as_list(customer.get("vatIds")) or [None])[0],
                    "createdAt": now_iso,
                }
            ],
            "orderCustomer": {
                "id": order_customer_id,
                "customerId": customer.get("id"),
                "email": customer.get("email"),
                "firstName": customer.get("firstName") or address.get("firstName") or "Test",
                "lastName": customer.get("lastName") or address.get("lastName") or "User",
                "salutationId": customer.get("salutationId") or address.get("salutationId"),
                "company": customer.get("company") or address.get("company"),
                "title": customer.get("title") or address.get("title"),
                "vatIds": _as_list(customer.get("vatIds")),
                "customerNumber": customer.get("customerNumber"),
                "createdAt": now_iso,
            },
            "lineItems": line_items,
        }
