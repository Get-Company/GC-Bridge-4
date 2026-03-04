from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from customer.models import Customer
from microtech.models import MicrotechJob
from microtech.services import MicrotechQueueService


class Command(BaseCommand):
    help = "Queues one Customer upsert from Django into Microtech."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nr",
            nargs="?",
            help="ERP Kundennummer (optional, falls --id genutzt wird).",
        )
        parser.add_argument(
            "--id",
            type=int,
            default=None,
            help="Django Customer ID.",
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

    def handle(self, *args, **options):
        erp_nr = (options.get("erp_nr") or "").strip()
        customer_id = options.get("id")
        no_wait = bool(options.get("no_wait"))
        wait_timeout = options.get("wait_timeout_seconds")

        if customer_id:
            customer = Customer.objects.filter(pk=customer_id).first()
        elif erp_nr:
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
        else:
            raise CommandError("Bitte erp_nr oder --id angeben.")

        if not customer:
            raise CommandError("Customer nicht gefunden.")

        queue = MicrotechQueueService()
        job = queue.enqueue(
            job_type=MicrotechJob.JobType.UPSERT_CUSTOMER,
            payload={"customer_id": customer.id},
            priority=30,
        )
        self.stdout.write(f"MicrotechJob #{job.id} eingereiht (upsert_customer).")
        if no_wait:
            return

        try:
            completed = queue.wait_for_terminal(job_id=job.id, timeout_seconds=wait_timeout)
        except TimeoutError as exc:
            raise CommandError(str(exc)) from exc

        if completed.status != MicrotechJob.Status.SUCCEEDED:
            logger.error("Microtech customer upsert failed for customer_id={}", customer.id)
            raise CommandError(completed.last_error or "Microtech customer upsert failed.")

        payload = completed.result or {}
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=True)))
