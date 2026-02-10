from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from shopware.services import ProductService


class Command(BaseCommand):
    help = "Prompt for a Shopware product number and log the JSON response."

    def add_arguments(self, parser):
        parser.add_argument(
            "product_number",
            nargs="?",
            help="Artikelnummer (productNumber) zum Nachschlagen.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Maximale Anzahl an Treffern (Default: 1).",
        )

    def handle(self, *args, **options):
        product_number = (options.get("product_number") or "").strip()
        if not product_number:
            product_number = input("Artikelnummer: ").strip()

        if not product_number:
            raise CommandError("Keine Artikelnummer angegeben.")

        service = ProductService()
        try:
            response = service.get_by_number(product_number, limit=options["limit"])
        except Exception as exc:  # pragma: no cover - network/runtime error
            logger.exception("Shopware request failed.")
            raise CommandError(str(exc)) from exc

        logger.info("Shopware response for productNumber={}", product_number)
        logger.info(
            "{}",
            json.dumps(response, ensure_ascii=True, indent=2, sort_keys=True),
        )
