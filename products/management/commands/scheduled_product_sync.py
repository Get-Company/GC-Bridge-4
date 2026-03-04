from __future__ import annotations

import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services import CommandRuntimeService
from microtech.services import MicrotechExpiredSpecialSyncService, microtech_connection


class Command(BaseCommand):
    help = (
        "Scheduler command: sync products from Microtech to Django, clear expired specials, "
        "update Microtech specials, and sync everything to Shopware."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optionales Limit fuer den Lauf (Debug/Test).",
        )
        parser.add_argument(
            "--exclude-inactive",
            action="store_true",
            help="Inaktive Microtech-Artikel beim Import ausschliessen.",
        )
        parser.add_argument(
            "--write-base-price-back",
            action="store_true",
            help=(
                "Schreibt den Django-Basispreis nach Microtech (Vk0.Preis) zurueck. "
                "Standard ist AUS, um versehentliche Preisfaktor-Fehler zu vermeiden."
            ),
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        include_inactive = not options.get("exclude_inactive", False)
        write_base_price_back = options.get("write_base_price_back", False)

        runtime = CommandRuntimeService().start(
            command_name="scheduled_product_sync",
            argv=sys.argv,
            metadata={
                "limit": limit,
                "include_inactive": include_inactive,
                "write_base_price_back": write_base_price_back,
            },
        )
        try:
            runtime.update(stage="1/4 microtech_to_django")
            self.stdout.write("1/4 Microtech -> Django import starten")
            call_command(
                "microtech_sync_products",
                all=True,
                include_inactive=include_inactive,
                preserve_is_active=True,
                limit=limit,
            )

            runtime.update(stage="2/4 clear_expired_specials")
            self.stdout.write("2/4 Abgelaufene Sonderpreise in Django bereinigen")
            expired_count, affected_product_ids = self._clear_expired_specials(now=timezone.now())
            self.stdout.write(
                f"Abgelaufene Sonderpreise bereinigt: {expired_count} Preiszeile(n), "
                f"{len(affected_product_ids)} Produkt(e)."
            )

            runtime.update(stage="3/4 writeback_microtech", affected_products=len(affected_product_ids))
            self.stdout.write("3/4 Microtech fuer abgelaufene Sonderpreise aktualisieren")
            updated_microtech, skipped_price_writes = self._sync_expired_specials_to_microtech(
                affected_product_ids,
                write_base_price_back=write_base_price_back,
            )
            if write_base_price_back:
                self.stdout.write(
                    "Microtech aktualisiert: "
                    f"{updated_microtech} Produkt(e), "
                    f"{skipped_price_writes} Preis-Writeback(s) wegen Plausibilitaetspruefung uebersprungen."
                )
            else:
                self.stdout.write(
                    f"Microtech aktualisiert: {updated_microtech} Produkt(e) "
                    "(nur Sonderpreisfelder, kein Basispreis-Writeback)."
                )

            runtime.update(stage="4/4 django_to_shopware")
            self.stdout.write("4/4 Django -> Shopware sync starten")
            call_command(
                "shopware_sync_products",
                all=True,
                limit=limit,
            )
            self.stdout.write(self.style.SUCCESS("Scheduled Product Sync erfolgreich abgeschlossen."))
        finally:
            runtime.close()

    @staticmethod
    def _clear_expired_specials(*, now):
        return MicrotechExpiredSpecialSyncService().clear_expired_specials(now=now)

    @staticmethod
    def _sync_expired_specials_to_microtech(
        affected_product_ids: set[int],
        *,
        write_base_price_back: bool = False,
    ) -> tuple[int, int]:
        with microtech_connection() as erp:
            updated_microtech, skipped = MicrotechExpiredSpecialSyncService().sync_expired_specials_to_microtech(
                erp=erp,
                affected_product_ids=affected_product_ids,
                write_base_price_back=write_base_price_back,
            )
        return updated_microtech, skipped

    @staticmethod
    def _is_suspicious_price_ratio(
        *,
        django_price,
        microtech_price,
    ) -> bool:
        return MicrotechExpiredSpecialSyncService._is_suspicious_price_ratio(
            django_price=django_price,
            microtech_price=microtech_price,
        )
