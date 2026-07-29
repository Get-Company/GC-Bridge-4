from __future__ import annotations

from django.core.management.base import CommandError

from core.management.base import MonitoredBaseCommand
from shopware.services import Shopware5CategoryMappingService


class Command(MonitoredBaseCommand):
    help = (
        "Liest die Shopware-5-Kategoriebäume inklusive Artikel-ERP-Nummern und "
        "ordnet sie lokalen Kategorien und Produkten zu."
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
            help="Anzahl der Kategorien/Artikel pro Shopware-5-Listenabfrage (maximal 1000).",
        )
        parser.add_argument(
            "--article-detail-workers",
            type=int,
            default=6,
            help="Parallele, rein lesende Shopware-5-Artikelabfragen (1 bis 12; Standard: 6).",
        )
        parser.add_argument(
            "--category",
            default="",
            help="Vergleicht eine Kategorie unter der angegebenen einzelnen --root-Kategorie ohne Änderungen zu schreiben.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Übernimmt Kategoriehierarchie und Produktzuordnungen lokal. Ohne --apply wird nur gelesen.",
        )
        parser.add_argument(
            "--replace-assignments",
            action="store_true",
            help="Entfernt beim --apply zusätzlich lokale Zuordnungen, die im Shopware-5-Teilbaum nicht mehr vorkommen.",
        )
        parser.add_argument(
            "--print-category-report",
            action="store_true",
            help=(
                "Gibt einen rein lesenden Kategorie-, Reihenfolge- und ERP-Produktabgleich "
                "mit den lokalen Kategorien aus."
            ),
        )

    def handle(self, *args, **options):
        if options["replace_assignments"] and not options["apply"]:
            raise CommandError("--replace-assignments erfordert --apply.")

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
            article_detail_workers=options["article_detail_workers"],
        )
        preview = service.preview(snapshot)
        reconciliation_report = (
            service.preview_reconciliation_report(snapshot) if options["print_category_report"] else None
        )
        self._write_preview(
            preview,
            print_category_report=options["print_category_report"],
            reconciliation_report=reconciliation_report,
        )

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

        result = service.apply(snapshot, replace_assignments=options["replace_assignments"])
        self.stdout.write(
            self.style.SUCCESS(
                "Shopware-5-Kategoriezuordnung übernommen: "
                f"Kategorien neu={result['created_categories']}, aktualisiert={result['updated_categories']}; "
                f"Produktzuordnungen neu={result['created_assignments']}, vorhanden={result['existing_assignments']}, "
                f"veraltet={result['stale_assignments']}, entfernt={result['removed_assignments']}; "
                f"fehlende ERP-Produkte={result['missing_products']}."
            )
        )

    def _write_preview(
        self,
        preview: dict,
        *,
        print_category_report: bool,
        reconciliation_report: dict | None,
    ) -> None:
        self.stdout.write(
            "Shopware-5-Quelle: "
            f"Wurzeln={', '.join(preview['roots'])}; Kategorien={preview['categories']}; "
            f"Artikel={preview['articles']}; Artikeldetails={preview['article_details']}; "
            f"ERP-Kategoriezuordnungen={preview['assignments']}."
        )
        if not print_category_report:
            return
        if reconciliation_report is None:
            return
        self.stdout.write(
            "Lokaler Leseabgleich: "
            f"Kategorien erkannt={reconciliation_report['recognized_categories']}/{reconciliation_report['categories']}; "
            f"Eltern korrekt={reconciliation_report['parent_matches']}/{reconciliation_report['categories']}; "
            f"Reihenfolge korrekt={reconciliation_report['position_matches']}/{reconciliation_report['categories']}; "
            f"Aktivstatus korrekt={reconciliation_report['active_matches']}/{reconciliation_report['categories']}."
        )
        for report in reconciliation_report["reports"]:
            state = "aktiv" if report["active"] else "inaktiv"
            self.stdout.write(
                f"[{report['id']}] {report['path']} (Position {report['position']}, {state}): "
                f"Shopware5-ERP={report['source_products']}; "
                f"im Projekt={report['project_products']}; zugeordnet={report['assigned_products']}."
            )
            local_category = report["local_category"]
            if local_category is None:
                self.stdout.write("  Lokal: nicht erkannt")
            else:
                self.stdout.write(
                    f"  Lokal: [{local_category['id']}] {' > '.join(local_category['path'])} "
                    f"(SW5={local_category['sw5_id'] or '-'}, SW6={local_category['sw6_id'] or '-'}; "
                    f"Position={local_category['position']}; {'aktiv' if local_category['active'] else 'inaktiv'})"
                )
                self.stdout.write(
                    "  Abgleich: "
                    f"Eltern={'OK' if report['parent_matches'] else 'abweichend'} "
                    f"(SW5={report['expected_parent_sw5_id'] or '-'}, "
                    f"lokal={report['actual_parent_sw5_id'] or '-'}); "
                    f"Reihenfolge={'OK' if report['position_matches'] else 'abweichend'}; "
                    f"Aktivstatus={'OK' if report['active_matches'] else 'abweichend'}."
                )
            if report["missing_in_project"]:
                self.stdout.write(f"  Fehlend im Projekt: {', '.join(report['missing_in_project'])}")
            if report["missing_assignment"]:
                self.stdout.write(f"  Im Projekt, aber nicht zugeordnet: {', '.join(report['missing_assignment'])}")
            if report["local_only_product_numbers"]:
                self.stdout.write(f"  Nur lokal zugeordnet: {', '.join(report['local_only_product_numbers'])}")

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
