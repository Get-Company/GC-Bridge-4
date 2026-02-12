from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from customer.models import Customer
from customer.services import CustomerUpsertMicrotechService


class Command(BaseCommand):
    help = "Upserts one Customer from Django into Microtech (Adressen/Anschriften/Ansprechpartner)."

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

    def handle(self, *args, **options):
        erp_nr = (options.get("erp_nr") or "").strip()
        customer_id = options.get("id")

        if customer_id:
            customer = Customer.objects.filter(pk=customer_id).first()
        elif erp_nr:
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
        else:
            raise CommandError("Bitte erp_nr oder --id angeben.")

        if not customer:
            raise CommandError("Customer nicht gefunden.")

        try:
            result = CustomerUpsertMicrotechService().upsert_customer(customer)
        except Exception as exc:  # pragma: no cover - COM/runtime errors
            logger.exception("Microtech customer upsert failed.")
            raise CommandError(str(exc)) from exc

        payload = {
            "customer_id": customer.id,
            "erp_nr": result.erp_nr,
            "shipping_ans_nr": result.shipping_ans_nr,
            "billing_ans_nr": result.billing_ans_nr,
            "is_new_customer": result.is_new_customer,
            "shopware_updated": result.shopware_updated,
        }
        logger.info("{}", json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
