from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from orders.models import Order
from orders.services import OrderUpsertMicrotechService


class Command(BaseCommand):
    help = "Upserts one Order from Django into Microtech (Vorgang)."

    def add_arguments(self, parser):
        parser.add_argument(
            "order_number",
            nargs="?",
            help="Shopware Bestellnummer (optional, falls --id genutzt wird).",
        )
        parser.add_argument(
            "--id",
            type=int,
            default=None,
            help="Django Order ID.",
        )

    def handle(self, *args, **options):
        order_number = (options.get("order_number") or "").strip()
        order_id = options.get("id")

        if order_id:
            order = Order.objects.filter(pk=order_id).first()
        elif order_number:
            order = Order.objects.filter(order_number=order_number).first()
        else:
            raise CommandError("Bitte order_number oder --id angeben.")

        if not order:
            raise CommandError("Order nicht gefunden.")

        try:
            result = OrderUpsertMicrotechService().upsert_order(order)
        except Exception as exc:
            logger.exception("Microtech order upsert failed.")
            raise CommandError(str(exc)) from exc

        payload = {
            "order_id": order.id,
            "order_number": order.order_number,
            "erp_order_id": result.erp_order_id,
            "is_new": result.is_new,
        }
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
