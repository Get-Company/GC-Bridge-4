from __future__ import annotations

from django.core.management.base import CommandError

from core.management.base import MonitoredBaseCommand
from shopware.services.shopware5_duplicate_category_merge import (
    DEFAULT_CANONICAL_CATEGORY_ROOTS,
    DEFAULT_TECHNICAL_CATEGORY_ROOT,
    Shopware5DuplicateCategoryTreeError,
    Shopware5DuplicateCategoryTreeMergeService,
)


class Command(MonitoredBaseCommand):
    help = (
        "Überträgt ausschließlich SW5-IDs vom Duplikatbaum Root > Deutsch/Schweiz auf die "
        "gleichnamigen kanonischen Root-Bäume."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            action="append",
            dest="roots",
            default=[],
            help="Kanonische Root-Kategorie. Mehrfach angeben; Standard: Deutsch und Schweiz.",
        )
        parser.add_argument(
            "--technical-root",
            default=DEFAULT_TECHNICAL_CATEGORY_ROOT,
            help="Oberste technische Duplikat-Root-Kategorie (Standard: Root).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Überträgt ausschließlich die SW5-IDs. Ohne --apply wird nur berichtet.",
        )
        parser.add_argument(
            "--delete-duplicate-subtrees",
            action="store_true",
            help=(
                "Löscht nach der SW5-ID-Übertragung Root > Deutsch und Root > Schweiz. "
                "Erfordert --apply und ist erst nach dem SW5-Lesesync vorgesehen."
            ),
        )

    def handle(self, *args, **options):
        if options["delete_duplicate_subtrees"] and not options["apply"]:
            raise CommandError("--delete-duplicate-subtrees erfordert --apply.")

        roots = [str(root).strip() for root in options["roots"] if str(root).strip()]
        service = Shopware5DuplicateCategoryTreeMergeService()
        try:
            preview = service.preview(
                root_names=roots or DEFAULT_CANONICAL_CATEGORY_ROOTS,
                technical_root_name=str(options["technical_root"] or "").strip(),
            )
        except Shopware5DuplicateCategoryTreeError as error:
            raise CommandError(str(error)) from error

        self._write_preview(preview)
        if not preview["can_apply"]:
            raise CommandError("Die Vorschau enthält Konflikte. Es wurden keine Kategorien verändert.")
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("Vorschau abgeschlossen. Es wurden keine Daten verändert."))
            return

        try:
            result = service.apply(
                root_names=roots or DEFAULT_CANONICAL_CATEGORY_ROOTS,
                technical_root_name=str(options["technical_root"] or "").strip(),
                delete_duplicate_subtrees=options["delete_duplicate_subtrees"],
            )
        except Shopware5DuplicateCategoryTreeError as error:
            raise CommandError(str(error)) from error

        deletion_text = (
            f" Gelöschte Duplikatkategorien={result['deleted_categories']}; "
            f"technisches Root gelöscht={'ja' if result['technical_root_deleted'] else 'nein'}."
            if options["delete_duplicate_subtrees"]
            else ""
        )
        self.stdout.write(
            self.style.SUCCESS(
                "SW5-IDs übertragen: "
                f"kanonisch gesetzt={result['transferred_sw5_ids']}; "
                f"am Duplikat geleert={result['cleared_duplicate_sw5_ids']}."
                + deletion_text
            )
        )

    def _write_preview(self, preview: dict) -> None:
        self.stdout.write(
            "Duplikatbaum: "
            f"technische Root={preview['technical_root']}; "
            f"Duplikatwurzeln={', '.join(preview['duplicate_roots'])}; "
            f"Duplikatkategorien={preview['duplicate_categories']}; "
            f"Produktzuordnungen im Duplikat={preview['duplicate_product_assignments']}; "
            f"Pfade abgeglichen={preview['matched_categories']}; "
            f"zu übertragende SW5-IDs={len(preview['transfers'])}."
        )
        for transfer in preview["transfers"]:
            self.stdout.write(
                f"  {transfer['path']}: Duplikat [{transfer['duplicate_id']}] SW5={transfer['duplicate_sw5_id']} "
                f"-> kanonisch [{transfer['canonical_id']}]"
            )
        for skipped in preview["skipped_without_sw5_id"]:
            self.stdout.write(
                f"  {skipped['path']}: keine Übertragung "
                f"(Duplikat-SW5={skipped['duplicate_sw5_id'] or '-'}, "
                f"kanonisch-SW5={skipped['canonical_sw5_id'] or '-'})"
            )
        for conflict in preview["conflicts"]:
            self.stderr.write(
                self.style.ERROR(
                    f"  Konflikt {conflict['path']}: Duplikat-SW5={conflict['duplicate_sw5_id']}, "
                    f"kanonisch-SW5={conflict['canonical_sw5_id']}"
                )
            )
        for path in preview["missing_canonical_paths"]:
            self.stderr.write(self.style.ERROR(f"  Kein kanonisches Gegenstück: {path}"))
        for path in preview["ambiguous_duplicate_paths"]:
            self.stderr.write(self.style.ERROR(f"  Mehrdeutiger Duplikatpfad: {path}"))
        for path in preview["ambiguous_canonical_paths"]:
            self.stderr.write(self.style.ERROR(f"  Mehrdeutiger kanonischer Pfad: {path}"))
