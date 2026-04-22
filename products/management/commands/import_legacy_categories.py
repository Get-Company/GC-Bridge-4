from __future__ import annotations

import sqlite3
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from products.models import Category


class Command(BaseCommand):
    help = "Importiert Legacy-Kategorien aus database.sql oder einer daraus erzeugten SQLite-Datei."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite-path",
            default="tmp/legacy_v3.sqlite3",
            help="Pfad zur Legacy-SQLite-Datei. Default: tmp/legacy_v3.sqlite3",
        )
        parser.add_argument(
            "--dump-path",
            default="database.sql",
            help="Pfad zur Legacy-MySQL-Dump-Datei. Default: database.sql",
        )
        parser.add_argument(
            "--rebuild-sqlite",
            action="store_true",
            help="Erzeugt die Legacy-SQLite-Datei aus --dump-path neu, auch wenn sie bereits existiert.",
        )

    def handle(self, *args, **options):
        sqlite_path = self._resolve_sqlite_path(
            sqlite_path_value=options["sqlite_path"],
            dump_path_value=options.get("dump_path", ""),
            rebuild_sqlite=options.get("rebuild_sqlite", False),
        )

        connection = sqlite3.connect(sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = list(self._load_rows(connection))
        finally:
            connection.close()

        if not rows:
            self.stdout.write("Keine Legacy-Kategorien gefunden.")
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic(), Category.objects.disable_mptt_updates():
            imported_by_erp_nr: dict[int, Category] = {}
            for row in rows:
                erp_nr = row["erp_nr"]
                title = str(row["title"] or "").strip()
                if not erp_nr or not title:
                    skipped_count += 1
                    continue

                defaults = {
                    "name": title,
                    "name_de": title,
                    "slug": self._build_slug(title=title, erp_nr=erp_nr),
                    "legacy_api_id": str(row["api_id"] or "").strip(),
                    "legacy_parent_erp_nr": self._clean_parent_erp_nr(row["erp_nr_parent"]),
                    "image": str(row["image"] or "").strip(),
                    "description": str(row["description"] or ""),
                    "legacy_changed_at": self._parse_legacy_datetime(row["erp_ltz_aend"]),
                    "parent": None,
                }
                category, created = Category.objects.update_or_create(
                    legacy_erp_nr=erp_nr,
                    defaults=defaults,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                imported_by_erp_nr[erp_nr] = category
                self._restore_created_at(category=category, value=row["created_at"])

            for row in rows:
                erp_nr = row["erp_nr"]
                category = imported_by_erp_nr.get(erp_nr)
                if category is None:
                    continue

                parent_erp_nr = self._clean_parent_erp_nr(row["erp_nr_parent"])
                parent = imported_by_erp_nr.get(parent_erp_nr) if parent_erp_nr else None
                parent_id = parent.pk if parent and parent.pk != category.pk else None
                Category.objects.filter(pk=category.pk).update(parent_id=parent_id)

        with transaction.atomic():
            Category.objects.rebuild()

        self.stdout.write(
            self.style.SUCCESS(
                "Legacy Kategorien importiert: "
                f"created={created_count}, updated={updated_count}, skipped={skipped_count}"
            )
        )

    def _resolve_sqlite_path(self, *, sqlite_path_value: str, dump_path_value: str, rebuild_sqlite: bool) -> Path:
        sqlite_path = Path(sqlite_path_value).resolve()
        dump_path = Path(dump_path_value).resolve() if dump_path_value else None

        if dump_path and (rebuild_sqlite or not sqlite_path.exists()):
            if not dump_path.exists():
                raise CommandError(f"Legacy Dump-Datei nicht gefunden: {dump_path}")
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            call_command("legacy_dump_to_sqlite", str(dump_path), str(sqlite_path), overwrite=True)

        if not sqlite_path.exists():
            raise CommandError(
                f"Legacy SQLite-Datei nicht gefunden: {sqlite_path}. "
                "Nutze --dump-path database.sql oder uebergib einen gueltigen --sqlite-path."
            )

        return sqlite_path

    @staticmethod
    def _load_rows(connection: sqlite3.Connection):
        query = """
            SELECT
                id,
                erp_nr,
                api_id,
                erp_nr_parent,
                title,
                image,
                description,
                erp_ltz_aend,
                created_at
            FROM bridge_category_entity
            ORDER BY id
        """
        yield from connection.execute(query)

    @staticmethod
    def _build_slug(*, title: str, erp_nr: int) -> str:
        base_slug = slugify(title) or "kategorie"
        return f"{base_slug}-{erp_nr}"

    @staticmethod
    def _clean_parent_erp_nr(value) -> int | None:
        if value in (None, "", 0, "0"):
            return None
        return int(value)

    @staticmethod
    def _parse_legacy_datetime(value):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _restore_created_at(self, *, category: Category, value) -> None:
        parsed = self._parse_legacy_datetime(value)
        if parsed is None:
            return
        Category.objects.filter(pk=category.pk).update(created_at=parsed)
