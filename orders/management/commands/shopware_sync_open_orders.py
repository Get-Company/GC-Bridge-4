from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from orders.services import OrderSyncService


class Command(BaseCommand):
    help = (
        "Loads open Shopware orders and upserts Order, OrderDetail, Customer, "
        "billing and shipping addresses into Django."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sales-channel-id",
            action="append",
            default=[],
            help="Optional: one or more sales channel IDs. If omitted, active ShopwareSettings are used.",
        )
        parser.add_argument(
            "--limit-orders",
            type=int,
            default=None,
            help="Optional: limit how many open orders are processed.",
        )

    def handle(self, *args, **options):
        sales_channel_ids = [value.strip() for value in options["sales_channel_id"] if value and value.strip()]
        limit_orders = options.get("limit_orders")

        try:
            summary = OrderSyncService().sync_open_orders(
                sales_channel_ids=sales_channel_ids or None,
                limit_orders=limit_orders,
            )
        except Exception as exc:  # pragma: no cover - runtime/network errors
            logger.exception("Shopware open-order sync failed.")
            raise CommandError(str(exc)) from exc

        logger.info("{}", json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
