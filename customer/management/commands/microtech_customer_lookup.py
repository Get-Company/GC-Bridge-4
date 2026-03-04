from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from customer.services import CustomerSyncService
from microtech.services import microtech_connection


class Command(BaseCommand):
    help = "Looks up a Microtech customer (AdrNr) and syncs it into Django."

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

        with microtech_connection() as erp:
            customer = CustomerSyncService().sync_from_microtech(erp_nr=erp_nr, erp=erp)

        payload = {
            "customer_id": customer.id,
            "erp_nr": customer.erp_nr,
            "name": customer.name,
            "email": customer.email,
            "addresses_count": customer.addresses.count(),
        }
        logger.info("Microtech response for customer erp_nr={}", erp_nr)
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=True)))
