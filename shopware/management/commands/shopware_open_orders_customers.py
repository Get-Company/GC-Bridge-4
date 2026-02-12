from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from shopware.models import ShopwareSettings
from shopware.services import CustomerService, OrderService


def _extract_customer_id(order_data: dict[str, Any]) -> str | None:
    order_customer = order_data.get("orderCustomer") or {}
    customer_id = order_customer.get("customerId")
    if customer_id:
        return customer_id

    nested_customer = order_customer.get("customer") or {}
    nested_customer_id = nested_customer.get("id")
    if nested_customer_id:
        return nested_customer_id

    return None


class Command(BaseCommand):
    help = (
        "Loads all open Shopware6 orders, extracts customer IDs from orderCustomer, "
        "and fetches customer details."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sales-channel-id",
            action="append",
            default=[],
            help="Optional: one or more Shopware sales channel IDs. If omitted, all active channels from ShopwareSettings are used.",
        )
        parser.add_argument(
            "--limit-customers",
            type=int,
            default=None,
            help="Optional: limits how many unique customers are requested.",
        )
        parser.add_argument(
            "--dump-json",
            action="store_true",
            help="Print full JSON for open orders and customer details.",
        )

    def handle(self, *args, **options):
        sales_channel_ids = [value.strip() for value in options["sales_channel_id"] if value and value.strip()]
        if not sales_channel_ids:
            sales_channel_ids = list(
                ShopwareSettings.objects.filter(is_active=True)
                .exclude(sales_channel_id="")
                .values_list("sales_channel_id", flat=True)
            )

        if not sales_channel_ids:
            raise CommandError("Keine Sales-Channel-IDs gefunden. Bitte in ShopwareSettings pflegen oder --sales-channel-id setzen.")

        order_service = OrderService()
        customer_service = CustomerService()

        all_orders: list[dict[str, Any]] = []
        for sales_channel_id in sales_channel_ids:
            response = order_service.list_all_open_by_sales_channel(sales_channel_id=sales_channel_id)
            orders = (response or {}).get("data", []) or []
            all_orders.extend(orders)
            logger.info(
                "SalesChannel {}: {} offene Bestellung(en) gefunden.",
                sales_channel_id,
                len(orders),
            )

        customer_ids: list[str] = []
        seen: set[str] = set()
        for order in all_orders:
            customer_id = _extract_customer_id(order)
            if not customer_id or customer_id in seen:
                continue
            seen.add(customer_id)
            customer_ids.append(customer_id)

        if options["limit_customers"]:
            customer_ids = customer_ids[: options["limit_customers"]]

        customer_details: list[dict[str, Any]] = []
        for customer_id in customer_ids:
            response = customer_service.get_by_id(customer_id)
            data = (response or {}).get("data", []) or []
            customer_details.append(
                {
                    "customer_id": customer_id,
                    "found": bool(data),
                    "customer": data[0] if data else None,
                }
            )

        summary = {
            "sales_channel_ids": sales_channel_ids,
            "open_orders_total": len(all_orders),
            "unique_customer_ids_total": len(seen),
            "customer_details_fetched": len(customer_details),
        }

        logger.info("{}", json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))

        if options["dump_json"]:
            logger.info(
                "{}",
                json.dumps(
                    {
                        "open_orders": all_orders,
                        "customer_details": customer_details,
                    },
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                    default=str,
                ),
            )
