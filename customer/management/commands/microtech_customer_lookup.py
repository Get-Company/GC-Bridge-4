from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from microtech.models import MicrotechJob
from microtech.services import MicrotechQueueService


class Command(BaseCommand):
    help = "Queues a Microtech customer lookup (AdrNr) and syncs it into Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nr",
            nargs="?",
            help="ERP Kundennummer (AdrNr).",
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
        no_wait = bool(options.get("no_wait"))
        wait_timeout = options.get("wait_timeout_seconds")
        if not erp_nr:
            erp_nr = input("Kundennummer (AdrNr): ").strip()
        if not erp_nr:
            raise CommandError("Keine Kundennummer angegeben.")

        queue = MicrotechQueueService()
        job = queue.enqueue(
            job_type=MicrotechJob.JobType.SYNC_CUSTOMER,
            payload={"erp_nr": erp_nr},
            priority=25,
        )
        self.stdout.write(f"MicrotechJob #{job.id} eingereiht (sync_customer).")
        if no_wait:
            return

        try:
            completed = queue.wait_for_terminal(job_id=job.id, timeout_seconds=wait_timeout)
        except TimeoutError as exc:
            raise CommandError(str(exc)) from exc

        if completed.status != MicrotechJob.Status.SUCCEEDED:
            logger.error("Microtech customer lookup failed for {}", erp_nr)
            raise CommandError(completed.last_error or "Microtech customer lookup failed.")

        payload = completed.result or {}
        logger.info("Microtech response for customer erp_nr={}", erp_nr)
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=True)))
