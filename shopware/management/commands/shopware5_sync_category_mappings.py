from __future__ import annotations

from django.core.management.base import CommandError

from core.management.base import MonitoredBaseCommand
from shopware.services import Shopware5CategoryMappingService


class Command(MonitoredBaseCommand):
    help = (
        "Ordnet ausschließlich SW5-IDs den vorhandenen SW6-Kategorien per vollständigem Kategorienpfad zu."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            action="append",
            dest="roots",
            default=[],
            help="Shopware-5-Wurzelkategorie. Mehrfach angeben; Standard: Deutsch und Schweiz.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=1000,
            help="Anzahl der Kategorien pro Shopware-5-Listenabfrage (maximal 1000).",
        )
        parser.add_argument(
            "--skip-inactive-categories",
            action="store_true",
            help="Überspringt inaktive SW5-Kategorien einschließlich ihrer Unterkategorien.",
        )
        parser.add_argument(
            "--category",
            default="",
            help="Zeigt eine einzelne Kategorie unter der angegebenen einzelnen --root-Kategorie ohne Änderungen.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Speichert ausschließlich sicher zugeordnete SW5-IDs. Ohne --apply wird nur gelesen.",
        )
        parser.add_argument(
            "--replace-assignments",
            action="store_true",
            help="Nicht mehr unterstützt: Produktzuordnungen werden ausschließlich aus Shopware 6 übernommen.",
        )
        parser.add_argument(
            "--print-category-report",
            action="store_true",
            help="Gibt für jede SW5-Kategorie den vollständigen Pfad und das Ergebnis der SW5-ID-Zuordnung aus.",
        )

    def handle(self, *args, **options):
        if options["replace_assignments"] and not options["apply"]:
            raise CommandError("--replace-assignments erfordert --apply.")
        if options["replace_assignments"]:
            raise CommandError(
                "--replace-assignments wird nicht mehr unterstützt. Produktzuordnungen stammen ausschließlich aus Shopware 6."
            )

        roots = [str(root).strip() for root in options["roots"] if str(root).strip()]
        category_name = str(options["category"] or "").strip()
        if category_name and options["apply"]:
            raise CommandError("--category ist eine reine Vergleichsvorschau und kann nicht mit --apply kombiniert werden.")
        if category_name and len(roots) != 1:
            raise CommandError("Für --category genau eine --root-Kategorie angeben.")
        service = Shopware5CategoryMappingService()
        snapshot = service.collect_snapshot(
            root_names=roots or ("Deutsch", "Schweiz"),
            page_size=options["page_size"],
            skip_inactive_categories=options["skip_inactive_categories"],
            include_product_assignments=False,
        )
        preview = service.preview_sw5_id_mapping(snapshot)
        self._write_preview(preview, print_category_report=options["print_category_report"])

        if category_name:
            comparison = service.preview_category_comparison(
                snapshot,
                root_name=roots[0],
                category_name=category_name,
            )
            self._write_category_comparison(comparison)
            self.stdout.write(self.style.SUCCESS("Kategorievergleich abgeschlossen. Es wurden keine Daten verändert."))
            return

        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("Vorschau abgeschlossen. Für die lokale Übernahme erneut mit --apply starten."))
            return

        result = service.apply_sw5_ids(snapshot)
        self.stdout.write(
            self.style.SUCCESS(
                "Shopware-5-ID-Zuordnung übernommen: "
                f"neu gesetzt={result['mapped']}; bereits korrekt={result['already_mapped']}; "
                f"übersprungen={result['skipped']}; lokale Kategorien ohne SW5-Gegenstück={result['local_without_source']}."
            )
        )

    def _write_preview(self, preview: dict, *, print_category_report: bool) -> None:
        self.stdout.write(
            "Shopware-5-ID-Abgleich: "
            f"Wurzeln={', '.join(preview['roots'])}; SW5-Kategorien={preview['source_categories']}; "
            f"neu zuzuordnen={preview['will_map']}; bereits korrekt={preview['already_mapped']}; "
            f"übersprungen={preview['skipped']}; inaktive Kategorien übersprungen={preview['skipped_inactive_categories']}; "
            f"lokale Kategorien ohne SW5-Gegenstück={len(preview['local_without_source'])}."
        )
        if not print_category_report:
            return
        for report in preview["reports"]:
            local_category = report["local_category"]
            self.stdout.write(
                f"[{report['sw5_id']}] {report['path']}: {self._mapping_status(report['status'])}"
            )
            if local_category is None:
                continue
            self.stdout.write(
                f"  Lokal: [{local_category['id']}] {local_category['name']} "
                f"(SW5={local_category['sw5_id'] or '-'}, SW6={local_category['sw6_id'] or '-'})"
            )
        for local_category in preview["local_without_source"]:
            self.stdout.write(
                f"  Nur lokal: [{local_category['id']}] {local_category['name']} "
                f"(SW6={local_category['sw6_id'] or '-'})"
            )

    @staticmethod
    def _mapping_status(status: str) -> str:
        labels = {
            "will_map": "SW5-ID wird gesetzt",
            "already_mapped": "bereits korrekt zugeordnet",
            "missing_local_category": "keine lokale Kategorie mit diesem vollständigen Pfad",
            "ambiguous_local_category": "mehrere lokale Kategorien mit diesem vollständigen Pfad",
            "conflicting_local_sw5_id": "lokale Kategorie besitzt eine abweichende SW5-ID",
            "sw5_id_owned_by_other_category": "SW5-ID ist bereits einer anderen lokalen Kategorie zugeordnet",
        }
        return labels.get(status, status)

    def _write_category_comparison(self, comparison: dict) -> None:
        source_category = comparison["source_category"]
        local_category = comparison["local_category"]
        self.stdout.write(
            "Shopware-5-Kategorie: "
            f"[{source_category['sw5_id']}] {source_category['path']} "
            f"(Position {source_category['position']})"
        )
        if local_category is None:
            self.stdout.write(self.style.WARNING("Lokale Kategorie: nicht erkannt; es wird nichts zugeordnet."))
        else:
            self.stdout.write(
                "Lokale Kategorie: "
                f"[{local_category['id']}] {local_category['path']} "
                f"(SW5={local_category['sw5_id'] or '-'}, SW6={local_category['sw6_id'] or '-'})"
            )

        source_product_numbers = comparison["source_product_numbers"]
        project_products = comparison["project_products"]
        assigned_count = sum(1 for product in project_products.values() if product["is_assigned"])
        self.stdout.write(
            "ERP-Abgleich: "
            f"Shopware5={len(source_product_numbers)}, Projekt vorhanden={len(project_products)}, "
            f"bereits zugeordnet={assigned_count}, "
            f"fehlend im Projekt={len(comparison['missing_in_project'])}, "
            f"nicht zugeordnet={len(comparison['missing_assignment'])}, "
            f"nur lokal={len(comparison['local_only_product_numbers'])}."
        )
        for product_number in source_product_numbers:
            product = project_products.get(product_number)
            if product is None:
                status = "fehlt im Projekt"
                name = ""
            elif product["is_assigned"]:
                status = "bereits zugeordnet"
                name = product["name"]
            else:
                status = "im Projekt, aber nicht zugeordnet"
                name = product["name"]
            name_suffix = f" — {name}" if name else ""
            self.stdout.write(f"  {product_number}: {status}{name_suffix}")
        for product_number in comparison["local_only_product_numbers"]:
            self.stdout.write(f"  {product_number}: nur in lokaler Kategorie")
