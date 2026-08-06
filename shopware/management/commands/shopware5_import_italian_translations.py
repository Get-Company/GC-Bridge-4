from __future__ import annotations

import json
import sys

from django.core.management.base import CommandError

from core.management.base import MonitoredBaseCommand
from core.services import CommandRuntimeService
from products.models import Product
from products.services import disable_product_auto_sync
from shopware.services.shopware5_translation_import import Shopware5ItalianTranslationImportService


class Command(MonitoredBaseCommand):
    help = "Importiert vorhandene italienische Produktübersetzungen aus Shopware5 nach Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern. Wenn leer, nutze --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Italienische Übersetzungen für alle lokalen Produkte importieren.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl zu verarbeitender Produkte.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Übersetzungen lesen und auswerten, aber nicht speichern.",
        )
        parser.add_argument(
            "--shop-id",
            default="",
            help="SW5-Shop-ID der italienischen Übersetzungen; überschreibt die automatische Erkennung.",
        )
        parser.add_argument(
            "--list-shops",
            action="store_true",
            help="SW5-Shops mit ID, Kategorie und Locale ausgeben, ohne Produktdaten zu ändern.",
        )

    def handle(self, *args, **options):
        erp_nrs = [str(value).strip() for value in options.get("erp_nrs") or [] if str(value).strip()]
        sync_all = options.get("all", False)
        limit = options.get("limit")
        dry_run = options.get("dry_run", False)
        italian_shop_id = str(options.get("shop_id") or "").strip()
        list_shops = options.get("list_shops", False)
        if list_shops:
            shops = Shopware5ItalianTranslationImportService().available_shops()
            self.stdout.write(json.dumps(shops, ensure_ascii=False, indent=2))
            return
        if not erp_nrs and not sync_all:
            raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

        queryset = Product.objects.all() if sync_all else Product.objects.filter(erp_nr__in=erp_nrs)
        ordered_queryset = queryset.order_by("erp_nr", "id")
        products = list(ordered_queryset[:limit] if limit else ordered_queryset)
        runtime = CommandRuntimeService().start(
            command_name="shopware5_import_italian_translations",
            argv=sys.argv,
            metadata={
                "mode": "all" if sync_all else "selected",
                "limit": limit,
                "dry_run": dry_run,
            },
        )
        try:
            runtime.update(stage="shopware5_to_django", total_products=len(products))
            with disable_product_auto_sync():
                summary = Shopware5ItalianTranslationImportService().import_products(
                    products,
                    dry_run=dry_run,
                    italian_shop_id=italian_shop_id or None,
                )
            runtime.update(stage="finished", **summary)
            self.stdout.write(
                self.style.SUCCESS(
                    "Shopware5 Italienisch-Import abgeschlossen: "
                    f"{summary['updated']} aktualisiert, "
                    f"{summary['unchanged']} unverändert, "
                    f"{summary['missing_translation']} ohne italienische Übersetzung, "
                    f"{summary['errors']} Fehler."
                )
            )
            if summary["errors"]:
                raise CommandError("Italienisch-Import abgeschlossen mit Fehlern.")
        finally:
            runtime.close()
