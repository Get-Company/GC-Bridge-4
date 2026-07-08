from __future__ import annotations

import sys
from collections.abc import Iterable

from django.core.management.base import CommandError
from django.db.models import Prefetch
from loguru import logger

from core.management.base import MonitoredBaseCommand
from core.services import CommandRuntimeService
from products.models import Price, Product
from shopware.services import Shopware5ProductSyncService


def _clean_erp_nrs(values: Iterable[str] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def _chunked(items: list[Product], size: int) -> Iterable[list[Product]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _prefetch_shopware5_queryset(queryset):
    return queryset.select_related("storage").prefetch_related(
        Prefetch(
            "prices",
            queryset=Price.objects.select_related("sales_channel").order_by("sales_channel_id", "id"),
            to_attr="prefetched_prices_for_shopware_sync",
        )
    )


class Command(MonitoredBaseCommand):
    help = "Sync products from Django to Shopware5: stock, prices and active state only."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern. Wenn leer, werden alle Produkte mit ERP-Nummer synchronisiert.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl zu synchronisierender Produkte.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Batch-Groesse fuer Shopware5 Sync (Default: 50).",
        )
        parser.add_argument(
            "--active-only",
            action="store_true",
            help="Nur lokal aktive Produkte synchronisieren. Standard ist alle, damit auch Inaktiv-Status geschrieben wird.",
        )

    def handle(self, *args, **options):
        erp_nrs = _clean_erp_nrs(options.get("erp_nrs"))
        limit = options.get("limit")
        batch_size = options.get("batch_size") or 50
        active_only = options.get("active_only", False)
        if batch_size <= 0:
            raise CommandError("Batch-Groesse muss groesser als 0 sein.")

        runtime = CommandRuntimeService().start(
            command_name="shopware5_sync_products",
            argv=sys.argv,
            metadata={
                "mode": "selected" if erp_nrs else "all",
                "limit": limit,
                "batch_size": batch_size,
                "active_only": active_only,
            },
        )
        try:
            queryset = Product.objects.all()
            if erp_nrs:
                queryset = queryset.filter(erp_nr__in=erp_nrs)
            else:
                queryset = queryset.exclude(erp_nr__isnull=True).exclude(erp_nr="")
            if active_only:
                queryset = queryset.filter(is_active=True)
            queryset = _prefetch_shopware5_queryset(queryset.order_by("erp_nr", "id"))
            if limit:
                queryset = queryset[:limit]

            products = list(queryset)
            total_products = len(products)
            service = Shopware5ProductSyncService()
            runtime.update(stage="prepare", total_products=total_products)

            summary = {
                "enabled": service.is_enabled,
                "processed": 0,
                "success": 0,
                "errors": 0,
                "skipped": 0,
            }
            if not products:
                self.stdout.write("Keine Produkte fuer Shopware5 Sync gefunden.")
                return summary

            total_batches = (total_products + batch_size - 1) // batch_size
            for batch_no, batch in enumerate(_chunked(products, batch_size), start=1):
                runtime.update(
                    stage="sync_batch",
                    processed=summary["processed"],
                    total_products=total_products,
                    current_batch_size=len(batch),
                )
                logger.info(
                    "Shopware5 sync batch {}/{} start: size={} products={}",
                    batch_no,
                    total_batches,
                    len(batch),
                    [product.erp_nr for product in batch],
                )
                batch_summary = service.sync_products(batch)
                summary["processed"] += int(batch_summary.get("processed") or 0)
                summary["success"] += int(batch_summary.get("success") or 0)
                summary["errors"] += int(batch_summary.get("errors") or 0)
                summary["skipped"] += int(batch_summary.get("skipped") or 0)
                logger.info("Shopware5 sync batch {} summary: {}", batch_no, batch_summary)

            runtime.update(stage="done", processed=summary["processed"], total_products=total_products)
            if summary["errors"]:
                self.stdout.write(
                    self.style.WARNING(
                        "Shopware5 Sync abgeschlossen mit "
                        f"{summary['errors']} Fehler(n), {summary['success']} erfolgreich."
                    )
                )
            elif not service.is_enabled:
                self.stdout.write("Shopware5 Sync ist deaktiviert.")
            else:
                self.stdout.write(self.style.SUCCESS(f"Shopware5 Sync abgeschlossen: {summary['success']} Produkt(e)."))
            return summary
        finally:
            runtime.close()
