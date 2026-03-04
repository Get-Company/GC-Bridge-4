from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from microtech.models import MicrotechJob
from microtech.services import MicrotechQueueService
from orders.models import Order


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
        parser.add_argument(
            "--no-wait",
            action="store_true",
            help="Nur einreihen, nicht auf Ergebnis warten.",
        )
        parser.add_argument(
            "--wait-timeout-seconds",
            type=int,
            default=None,
            help="Optionales Timeout fuer --wait.",
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
            retention="14 days",
            encoding="utf-8",
        )
        return sink_id, path

    def handle(self, *args, **options):
        order_number = (options.get("order_number") or "").strip()
        order_id = options.get("id")
        log_file = (options.get("log_file") or "").strip() or "tmp/logs/microtech_order_upsert.log"
        no_wait = bool(options.get("no_wait"))
        wait_timeout = options.get("wait_timeout_seconds")
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

            queue = MicrotechQueueService()
            job = queue.enqueue(
                job_type=MicrotechJob.JobType.UPSERT_ORDER,
                payload={
                    "order_id": order.id,
                    "log_file": str(log_path),
                },
                priority=35,
            )
            self.stdout.write(f"MicrotechJob #{job.id} eingereiht (upsert_order).")
            if no_wait:
                return

            try:
                completed = queue.wait_for_terminal(job_id=job.id, timeout_seconds=wait_timeout)
            except TimeoutError as exc:
                raise CommandError(str(exc)) from exc

            if completed.status != MicrotechJob.Status.SUCCEEDED:
                logger.error("Microtech order upsert failed.")
                raise CommandError(completed.last_error or "Microtech order upsert failed.")

            payload = dict(completed.result or {})
            payload["log_file"] = str(log_path)
            logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
            self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=True)))
        finally:
            logger.info("Finished Microtech order upsert run. log_file={}", log_path)
            logger.remove(sink_id)
