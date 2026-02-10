from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from microtech.services.artikel import MicrotechArtikelService
from microtech.services.connection import microtech_connection


class Command(BaseCommand):
    help = "Prompt for an article number and log the Microtech COM response."

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

        try:
            with microtech_connection() as erp:
                service = MicrotechArtikelService(erp=erp)
                found = service.find(artikel_nr)
                name = service.get_name() if found else None
        except Exception as exc:  # pragma: no cover - COM/runtime error
            logger.exception("Microtech request failed.")
            raise CommandError(str(exc)) from exc

        payload = {
            "artikel_nr": artikel_nr,
            "found": bool(found),
            "name": name,
        }
        logger.info("Microtech response for artikel_nr={}", artikel_nr)
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
