from __future__ import annotations

import sys

from django.core.management.base import BaseCommand
from loguru import logger

from core.logging import add_managed_file_sink
from core.services import CommandRuntimeService


class Command(BaseCommand):
    help = "Scrapt Mappei-Produktseiten und speichert Preise (nur bei Änderung)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product",
            type=str,
            default=None,
            metavar="ARTIKELNR",
            help="Nur diesen Artikel scrapen (z.B. --product 104046).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl Produkte (Debug/Test).",
        )
        parser.add_argument(
            "--log-file",
            type=str,
            default="",
            help="Optionaler Pfad für den Log. Standard ist der verwaltete Loguru-Pfad.",
        )

    def handle(self, *args, **options):
        single_artikelnr = options.get("product")
        limit = options.get("limit")
        log_file = (options.get("log_file") or "").strip()

        sink_id, log_path = add_managed_file_sink(
            log_name="scrape_mappei",
            category="weekly",
            log_file=log_file or None,
            diagnose=True,
        )

        runtime = CommandRuntimeService().start(
            command_name="scrape_mappei",
            argv=sys.argv,
            metadata={
                "single_artikelnr": single_artikelnr,
                "limit": limit,
                "log_file": str(log_path),
            },
        )

        try:
            logger.info(
                "Mappei scraper started. single_artikelnr={} limit={} log_file={}",
                single_artikelnr,
                limit,
                log_path,
            )

            from mappei.services.scraper import run_scraper

            result = run_scraper(limit=limit, single_artikelnr=single_artikelnr)

            logger.info(
                "Mappei scraper finished. processed={} snapshots_created={} errors={}",
                result["processed"],
                result["snapshots_created"],
                result["errors"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Mappei Scraper abgeschlossen: "
                    f"{result['processed']} Produkte, "
                    f"{result['snapshots_created']} neue Preissnapshots, "
                    f"{result['errors']} Fehler."
                )
            )
        except Exception:
            logger.exception("Mappei scraper failed. log_file={}", log_path)
            raise
        finally:
            logger.remove(sink_id)
            runtime.close()
