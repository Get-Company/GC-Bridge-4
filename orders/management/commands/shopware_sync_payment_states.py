from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from orders.services.payment_status import OrderPaymentStatusService


class Command(BaseCommand):
    help = "Refresh payment statuses of all imported orders from Shopware (no order reimport)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report changes without writing them.")
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        try:
            summary = OrderPaymentStatusService().sync(
                dry_run=options["dry_run"], batch_size=options["batch_size"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(summary, sort_keys=True))
        if summary["orders_failed"]:
            raise CommandError(f"Zahlungsstatus-Abgleich: {summary['orders_failed']} Bestellung(en) fehlgeschlagen.")
