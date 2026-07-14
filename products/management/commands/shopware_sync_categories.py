from __future__ import annotations

import sys

from loguru import logger

from core.management.base import MonitoredBaseCommand
from core.services import CommandRuntimeService
from products.services import ShopwareCategorySyncService


class Command(MonitoredBaseCommand):
    help = "Importiert Kategorien inklusive Shopware-6-ID, SEO-Feldern und Übersetzungen nach Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optionales Limit für den Lauf.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Shopware-Batchgröße pro API-Request.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        page_size = options.get("page_size") or 100
        runtime = CommandRuntimeService().start(
            command_name="shopware_sync_categories",
            argv=sys.argv,
            metadata={
                "limit": limit,
                "page_size": page_size,
            },
        )
        try:
            runtime.update(stage="shopware_to_django")
            summary = ShopwareCategorySyncService().sync_from_shopware(
                limit=limit,
                page_size=page_size,
            )
            runtime.update(stage="finished", **summary)
            logger.info("Shopware category sync finished. summary={}", summary)
            self.stdout.write(
                self.style.SUCCESS(
                    "Shopware-Kategorie-Sync abgeschlossen: "
                    f"{summary['seen']} gesehen, "
                    f"{summary['created']} neu, "
                    f"{summary['updated']} aktualisiert, "
                    f"{summary['skipped']} übersprungen."
                )
            )
        except Exception:
            logger.exception("Shopware category sync failed.")
            raise
        finally:
            runtime.close()
