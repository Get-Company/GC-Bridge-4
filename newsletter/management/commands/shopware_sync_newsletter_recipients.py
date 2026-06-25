from __future__ import annotations

import sys

from loguru import logger

from core.management.base import MonitoredBaseCommand
from core.services import CommandRuntimeService
from newsletter.services import NewsletterRecipientSyncService


class Command(MonitoredBaseCommand):
    help = "Synchronisiert Newsletter-Empfaenger aus Shopware nach Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optionales Limit fuer den Lauf.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Shopware-Batchgroesse pro API-Request.",
        )
        parser.add_argument(
            "--status",
            type=str,
            default="",
            help="Optionaler Shopware-Statusfilter.",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="",
            help="Optionaler E-Mail-Suchfilter.",
        )
        parser.add_argument(
            "--mark-missing",
            action="store_true",
            help="Nur bei Vollsync: lokal vorhandene, in Shopware fehlende Empfaenger markieren.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        page_size = options.get("page_size") or 100
        status = (options.get("status") or "").strip()
        email = (options.get("email") or "").strip()
        mark_missing = bool(options.get("mark_missing", False))

        runtime = CommandRuntimeService().start(
            command_name="shopware_sync_newsletter_recipients",
            argv=sys.argv,
            metadata={
                "limit": limit,
                "page_size": page_size,
                "status": status,
                "email": email,
                "mark_missing": mark_missing,
            },
        )
        try:
            runtime.update(stage="shopware_to_django")
            logger.info(
                "Newsletter recipient sync started. limit={} page_size={} status={} email={} mark_missing={}",
                limit,
                page_size,
                status,
                email,
                mark_missing,
            )
            summary = NewsletterRecipientSyncService().sync_from_shopware(
                limit=limit,
                page_size=page_size,
                status=status,
                email=email,
                mark_missing=mark_missing,
            )
            runtime.update(stage="finished", **summary)
            logger.info("Newsletter recipient sync finished. summary={}", summary)
            self.stdout.write(
                self.style.SUCCESS(
                    "Newsletter-Sync abgeschlossen: "
                    f"{summary['seen']} gesehen, "
                    f"{summary['created']} neu, "
                    f"{summary['updated']} aktualisiert, "
                    f"{summary['failed']} Fehler, "
                    f"{summary['marked_missing']} als fehlend markiert."
                )
            )
        except Exception:
            logger.exception("Newsletter recipient sync failed.")
            raise
        finally:
            runtime.close()
