from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from core.logging import add_managed_file_sink
from microtech.services import microtech_connection
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
        parser.add_argument(
            "--log-file",
            type=str,
            default="tmp/logs/microtech_order_upsert.log",
            help="Pfad fuer den detaillierten Vorgangs-Log.",
        )

    @staticmethod
    def _add_file_sink(log_file: str) -> tuple[int, Path]:
        return add_managed_file_sink(
            log_name="microtech_order_upsert",
            category="monthly",
            log_file=log_file,
            rotation="10 MB",
            diagnose=True,
        )

    def handle(self, *args, **options):
        order_number = (options.get("order_number") or "").strip()
        order_id = options.get("id")
        log_file = (options.get("log_file") or "").strip()
        sink_id, log_path = self._add_file_sink(log_file)

        logger.info("Starting Microtech order upsert run. log_file={}", log_path)
        try:
            if order_id:
                order = Order.objects.filter(pk=order_id).first()
            elif order_number:
                order = Order.objects.filter(order_number=order_number).first()
            else:
                raise CommandError("Bitte order_number oder --id angeben.")

            if not order:
                raise CommandError("Order nicht gefunden.")

            logger.info(
                "Selected order: id={}, order_number='{}', api_id='{}', erp_order_id='{}'.",
                order.id,
                order.order_number,
                order.api_id,
                order.erp_order_id,
            )

            with microtech_connection() as erp:
                result = OrderUpsertMicrotechService().upsert_order(order, erp=erp)

            payload = {
                "order_id": order.id,
                "order_number": order.order_number,
                "erp_order_id": result.erp_order_id,
                "is_new": result.is_new,
                "rule_id": result.rule_debug.rule_id,
                "rule_name": result.rule_debug.rule_name,
                "payment_position_requested": result.rule_debug.payment_position_requested,
                "payment_position_added": result.rule_debug.payment_position_added,
                "payment_position_reason": result.rule_debug.payment_position_reason,
                "payment_position_erp_nr": result.rule_debug.payment_position_erp_nr,
                "payment_position_amount": (
                    str(result.rule_debug.payment_position_amount)
                    if result.rule_debug.payment_position_amount is not None
                    else ""
                ),
                "dataset_actions_total": result.rule_debug.dataset_actions_total,
                "dataset_actions_applied": result.rule_debug.dataset_actions_applied,
                "dataset_set_field_requested": result.rule_debug.dataset_set_field_requested,
                "dataset_set_field_applied": result.rule_debug.dataset_set_field_applied,
                "dataset_create_position_requested": result.rule_debug.dataset_create_position_requested,
                "dataset_create_position_applied": result.rule_debug.dataset_create_position_applied,
                "dataset_created_position_erp_nrs": list(result.rule_debug.dataset_created_position_erp_nrs),
                "dataset_actions_note": result.rule_debug.dataset_actions_note,
                "log_file": str(log_path),
            }
            logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
            self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=True)))
        finally:
            logger.info("Finished Microtech order upsert run. log_file={}", log_path)
            logger.remove(sink_id)
