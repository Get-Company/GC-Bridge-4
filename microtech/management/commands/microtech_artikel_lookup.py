from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from microtech.services import microtech_connection
from microtech.services.artikel import MicrotechArtikelService


class Command(BaseCommand):
    help = "Looks up an article directly from Microtech ERP."

    def add_arguments(self, parser):
        parser.add_argument(
            "artikel_nr",
            nargs="?",
            help="Artikelnummer (Nr) zum Nachschlagen.",
        )

    def handle(self, *args, **options):
        artikel_nr = (options.get("artikel_nr") or "").strip()
        if not artikel_nr:
            artikel_nr = input("Artikelnummer: ").strip()

        if not artikel_nr:
            raise CommandError("Keine Artikelnummer angegeben.")

        with microtech_connection() as erp:
            result = Command.lookup_with_erp(artikel_nr=artikel_nr, erp=erp)

        logger.info("Microtech response for artikel_nr={}", artikel_nr)
        logger.info("{}", json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(json.dumps(result, ensure_ascii=True)))

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
