from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from microtech.models import MicrotechJob
from microtech.services.artikel import MicrotechArtikelService
from microtech.services import MicrotechQueueService


class Command(BaseCommand):
    help = "Queues an article lookup in the dedicated Microtech worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "artikel_nr",
            nargs="?",
            help="Artikelnummer (Nr) zum Nachschlagen.",
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
        artikel_nr = (options.get("artikel_nr") or "").strip()
        no_wait = bool(options.get("no_wait"))
        wait_timeout = options.get("wait_timeout_seconds")
        if not artikel_nr:
            artikel_nr = input("Artikelnummer: ").strip()

        if not artikel_nr:
            raise CommandError("Keine Artikelnummer angegeben.")

        queue = MicrotechQueueService()
        job = queue.enqueue(
            job_type=MicrotechJob.JobType.LOOKUP_ARTICLE,
            payload={"artikel_nr": artikel_nr},
            priority=20,
        )
        self.stdout.write(f"MicrotechJob #{job.id} eingereiht (lookup_article).")
        if no_wait:
            return

        try:
            completed = queue.wait_for_terminal(job_id=job.id, timeout_seconds=wait_timeout)
        except TimeoutError as exc:
            raise CommandError(str(exc)) from exc

        if completed.status != MicrotechJob.Status.SUCCEEDED:
            raise CommandError(completed.last_error or "Microtech article lookup failed.")

        payload = completed.result or {}
        logger.info("Microtech response for artikel_nr={}", artikel_nr)
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=True)))

    @staticmethod
    def lookup_with_erp(*, artikel_nr: str, erp) -> dict:
        service = MicrotechArtikelService(erp=erp)
        found = service.find(artikel_nr)
        name = service.get_name() if found else None
        return {
            "artikel_nr": artikel_nr,
            "found": bool(found),
            "name": name,
        }
