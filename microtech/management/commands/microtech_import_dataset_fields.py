from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from microtech.services.dataset_field_catalog_import import (
    CORE_DATASET_SELECTORS,
    MicrotechDatasetFieldCatalogImportService,
)


class Command(BaseCommand):
    help = "Importiert Microtech-Dataset-Felder aus FELD_25.LST in den Feldkatalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="FELD_25.LST",
            help="Pfad zur Feldliste (Default: FELD_25.LST im Projektroot).",
        )
        parser.add_argument(
            "--dataset",
            action="append",
            dest="datasets",
            help=(
                "Dataset-Filter, mehrfach nutzbar. Beispiel: "
                "--dataset 'Vorgang - Vorgange' --dataset 'Adressen - Adressen'"
            ),
        )
        parser.add_argument(
            "--include-nested",
            action="store_true",
            help="Importiert zusaetzlich NestedDataSet-Felder.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur parsen, keine Datenbankaenderungen schreiben.",
        )

    def handle(self, *args, **options):
        file_path = Path(str(options["file"])).expanduser().resolve()
        dataset_selectors = tuple(options.get("datasets") or CORE_DATASET_SELECTORS)
        top_level_only = not bool(options.get("include_nested"))
        dry_run = bool(options.get("dry_run"))

        service = MicrotechDatasetFieldCatalogImportService()
        try:
            report = service.import_from_list_file(
                file_path=file_path,
                selectors=dataset_selectors,
                top_level_only=top_level_only,
                dry_run=dry_run,
            )
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(f"Import fehlgeschlagen: {exc}") from exc

        selectors_text = ", ".join(dataset_selectors)
        self.stdout.write(self.style.NOTICE(f"Datei: {file_path}"))
        self.stdout.write(self.style.NOTICE(f"Datasets: {selectors_text}"))
        self.stdout.write(self.style.NOTICE(f"Top-Level only: {top_level_only}"))
        self.stdout.write(self.style.NOTICE(f"Dry-Run: {report.dry_run}"))
        self.stdout.write(
            self.style.SUCCESS(
                "Parse Ergebnis: "
                f"datasets={report.parsed_datasets}, fields={report.parsed_fields}"
            )
        )
        if not report.dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "DB Ergebnis: "
                    f"created_datasets={report.created_datasets}, "
                    f"updated_datasets={report.updated_datasets}, "
                    f"created_fields={report.created_fields}, "
                    f"updated_fields={report.updated_fields}, "
                    f"deactivated_fields={report.deactivated_fields}"
                )
            )
