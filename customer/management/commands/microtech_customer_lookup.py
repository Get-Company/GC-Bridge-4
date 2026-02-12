from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from customer.services import CustomerSyncService


class Command(BaseCommand):
    help = "Loads a customer by ERP number (AdrNr) from Microtech and syncs it into Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nr",
            nargs="?",
            help="ERP Kundennummer (AdrNr).",
        )

    def handle(self, *args, **options):
        erp_nr = (options.get("erp_nr") or "").strip()
        if not erp_nr:
            erp_nr = input("Kundennummer (AdrNr): ").strip()
        if not erp_nr:
            raise CommandError("Keine Kundennummer angegeben.")

        try:
            customer = CustomerSyncService().sync_from_microtech(erp_nr)
        except Exception as exc:  # pragma: no cover - runtime/COM error path
            logger.exception("Microtech customer lookup failed for {}", erp_nr)
            raise CommandError(str(exc)) from exc

        payload = {
            "erp_nr": customer.erp_nr,
            "name": customer.name,
            "email": customer.email,
            "addresses_count": customer.addresses.count(),
        }
        logger.info("Microtech response for customer erp_nr={}", erp_nr)
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
