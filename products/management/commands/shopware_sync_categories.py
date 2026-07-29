from __future__ import annotations

import sys

from django.core.management.base import CommandError
from loguru import logger

from core.management.base import MonitoredBaseCommand
from core.services import CommandRuntimeService
from products.services import ShopwareCategorySyncService


class Command(MonitoredBaseCommand):
    help = "Importiert Kategorien inklusive Shopware-6-ID, SEO-Feldern und Übersetzungen nach Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            action="append",
            dest="roots",
            default=[],
            help="SW6-Wurzelkategorie. Mehrfach angeben; Standard: Deutsch und Schweiz.",
        )
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
        parser.add_argument(
            "--skip-product-assignments",
            action="store_true",
            help="Nur Kategorien und Reihenfolge aus SW6 übernehmen; Produktzuordnungen unverändert lassen.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        page_size = options.get("page_size") or 100
        roots = [str(root).strip() for root in options.get("roots", []) if str(root).strip()]
        skip_product_assignments = options.get("skip_product_assignments", False)
        if limit is not None and not skip_product_assignments:
            raise CommandError("--limit erfordert --skip-product-assignments, damit keine unvollständigen Zuordnungen übernommen werden.")
        runtime = CommandRuntimeService().start(
            command_name="shopware_sync_categories",
            argv=sys.argv,
            metadata={
                "limit": limit,
                "page_size": page_size,
                "roots": roots or ["Deutsch", "Schweiz"],
                "skip_product_assignments": skip_product_assignments,
            },
        )
        try:
            runtime.update(stage="shopware_to_django")
            summary = ShopwareCategorySyncService().sync_from_shopware(
                limit=limit,
                page_size=page_size,
                root_names=tuple(roots or ("Deutsch", "Schweiz")),
                sync_product_assignments=not skip_product_assignments,
            )
            runtime.update(stage="finished", **summary)
            logger.info("Shopware category sync finished. summary={}", summary)
            self.stdout.write(
                self.style.SUCCESS(
                    "Shopware-Kategorie-Sync abgeschlossen: "
                    f"{summary['scoped']}/{summary['seen']} im Zielbaum, "
                    f"{summary['created']} neu, "
                    f"{summary['updated']} aktualisiert, "
                    f"{summary['ignored_outside_roots']} außerhalb der Zielbäume ignoriert; "
                    f"Produktzuordnungen neu={summary['created_assignments']}, "
                    f"vorhanden={summary['existing_assignments']}, entfernt={summary['removed_assignments']}; "
                    f"fehlende ERP-Produkte={summary['missing_products']}."
                )
            )
        except Exception:
            logger.exception("Shopware category sync failed.")
            raise
        finally:
            runtime.close()
