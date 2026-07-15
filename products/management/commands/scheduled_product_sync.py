from __future__ import annotations

import sys
from pathlib import Path

from django.core.management import call_command
from core.management.base import MonitoredBaseCommand
from django.utils import timezone
from loguru import logger

from core.logging import add_managed_file_sink
from core.services import CommandRuntimeService
from microtech.services import MicrotechExpiredSpecialSyncService, microtech_connection


class Command(MonitoredBaseCommand):
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
                "Veraltet und nur fuer bestehende Aufrufe erhalten. Preisbäume werden "
                "bei abgelaufenen Sonderpreisen immer vollständig nach Microtech geschrieben."
            ),
        )
        parser.add_argument(
            "--skip-force-images",
            action="store_true",
            help="Shopware-Bilder nicht vollstaendig loeschen, neu hochladen und neu zuordnen.",
        )
        parser.add_argument(
            "--log-file",
            type=str,
            default="",
            help="Optionaler Pfad fuer den detaillierten Scheduler-Log. Standard ist der verwaltete Loguru-Pfad.",
        )

    @staticmethod
    def _add_file_sink(log_file: str) -> tuple[int, Path]:
        return add_managed_file_sink(
            log_name="scheduled_product_sync",
            category="weekly",
            log_file=log_file or None,
            diagnose=True,
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        include_inactive = not options.get("exclude_inactive", False)
        write_base_price_back = options.get("write_base_price_back", False)
        force_images = not options.get("skip_force_images", False)
        log_file = (options.get("log_file") or "").strip()
        sink_id, log_path = self._add_file_sink(log_file)

        runtime = CommandRuntimeService().start(
            command_name="scheduled_product_sync",
            argv=sys.argv,
            metadata={
                "limit": limit,
                "include_inactive": include_inactive,
                "write_base_price_back": write_base_price_back,
                "force_images": force_images,
                "log_file": str(log_path),
            },
        )
        try:
            logger.info(
                (
                    "Scheduled product sync started. limit={} include_inactive={} "
                    "write_base_price_back={} force_images={} log_file={}"
                ),
                limit,
                include_inactive,
                write_base_price_back,
                force_images,
                log_path,
            )
            total_stages = 5 if force_images else 4
            runtime.update(stage=f"1/{total_stages} microtech_to_django")
            self.stdout.write(f"1/{total_stages} Microtech -> Django import starten")
            call_command(
                "microtech_sync_products",
                all=True,
                include_inactive=include_inactive,
                preserve_is_active=True,
                limit=limit,
            )

            runtime.update(stage=f"2/{total_stages} clear_expired_specials")
            self.stdout.write(f"2/{total_stages} Abgelaufene Sonderpreise in Django bereinigen")
            expired_count, affected_product_ids = self._clear_expired_specials(now=timezone.now())
            logger.info(
                "Scheduled product sync cleared expired specials. expired_count={} affected_products={}",
                expired_count,
                len(affected_product_ids),
            )
            self.stdout.write(
                f"Abgelaufene Sonderpreise bereinigt: {expired_count} Preiszeile(n), "
                f"{len(affected_product_ids)} Produkt(e)."
            )

            runtime.update(stage=f"3/{total_stages} writeback_microtech", affected_products=len(affected_product_ids))
            self.stdout.write(f"3/{total_stages} Microtech fuer abgelaufene Sonderpreise aktualisieren")
            updated_microtech, skipped_price_writes = self._sync_expired_specials_to_microtech(
                affected_product_ids,
                write_base_price_back=write_base_price_back,
            )
            logger.info(
                "Scheduled product sync updated Microtech. updated_products={} skipped_price_writes={}",
                updated_microtech,
                skipped_price_writes,
            )
            self.stdout.write(
                f"Microtech aktualisiert: {updated_microtech} Produkt(e) "
                "mit vollständigen Preisbäumen."
            )

            runtime.update(stage=f"4/{total_stages} django_to_shopware")
            self.stdout.write(f"4/{total_stages} Django -> Shopware sync starten")
            call_command(
                "shopware_sync_products",
                all=True,
                limit=limit,
                skip_images=force_images,
            )
            if force_images:
                runtime.update(stage="5/5 force_shopware_images")
                self.stdout.write("5/5 Shopware-Bilder vollstaendig neu hochladen")
                call_command(
                    "shopware_force_product_image_uploads",
                    all=True,
                    limit=limit,
                )
            logger.info("Scheduled product sync finished successfully. log_file={}", log_path)
            self.stdout.write(self.style.SUCCESS("Scheduled Product Sync erfolgreich abgeschlossen."))
        except Exception:
            logger.exception("Scheduled product sync failed. log_file={}", log_path)
            raise
        finally:
            logger.remove(sink_id)
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
