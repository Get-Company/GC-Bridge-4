from __future__ import annotations

import sqlite3
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from products.models import Category, Product


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
        parser.add_argument(
            "--skip-product-assignments",
            action="store_true",
            help="Importiert nur Kategorien und ueberspringt Produkt-Kategorie-Zuweisungen.",
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
            assignment_rows = (
                []
                if options.get("skip_product_assignments", False)
                else list(self._load_product_category_assignment_rows(connection))
            )
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

        assignment_result = None
        if assignment_rows:
            assignment_result = self._import_product_category_assignments(assignment_rows)

        self.stdout.write(
            self.style.SUCCESS(
                "Legacy Kategorien importiert: "
                f"created={created_count}, updated={updated_count}, skipped={skipped_count}"
            )
        )
        if assignment_result is not None:
            self.stdout.write(
                self.style.SUCCESS(
                    "Legacy Produkt-Kategorie-Zuweisungen importiert: "
                    f"source_rows={assignment_result['source_rows']}, "
                    f"created={assignment_result['created']}, "
                    f"existing={assignment_result['existing']}, "
                    f"missing_products={assignment_result['missing_products']}, "
                    f"missing_categories={assignment_result['missing_categories']}, "
                    f"skipped={assignment_result['skipped']}"
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

    @classmethod
    def _load_product_category_assignment_rows(cls, connection: sqlite3.Connection):
        required_tables = {
            "bridge_product_category_entity",
            "bridge_product_entity",
            "bridge_category_entity",
        }
        if not cls._tables_exist(connection, required_tables):
            return

        query = """
            SELECT
                product_categories.product_id AS legacy_product_id,
                TRIM(COALESCE(products.erp_nr, '')) AS product_erp_nr,
                product_categories.category_id AS legacy_category_id,
                categories.erp_nr AS category_erp_nr
            FROM bridge_product_category_entity product_categories
            INNER JOIN bridge_product_entity products
                ON products.id = product_categories.product_id
            INNER JOIN bridge_category_entity categories
                ON categories.id = product_categories.category_id
            ORDER BY product_categories.product_id, product_categories.category_id
        """
        yield from connection.execute(query)

    @staticmethod
    def _tables_exist(connection: sqlite3.Connection, table_names: set[str]) -> bool:
        placeholders = ", ".join("?" for _ in table_names)
        query = f"""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name IN ({placeholders})
        """
        existing_tables = {row["name"] for row in connection.execute(query, tuple(table_names))}
        return table_names.issubset(existing_tables)

    def _import_product_category_assignments(self, rows: list[sqlite3.Row]) -> dict[str, int]:
        source_rows = len(rows)
        skipped_count = 0
        missing_product_keys: set[str] = set()
        missing_category_keys: set[int] = set()
        pairs: set[tuple[str, int]] = set()

        for row in rows:
            product_erp_nr = str(row["product_erp_nr"] or "").strip()
            category_erp_nr = row["category_erp_nr"]
            if not product_erp_nr or not category_erp_nr:
                skipped_count += 1
                continue
            pairs.add((product_erp_nr, int(category_erp_nr)))

        product_erp_numbers = {product_erp_nr for product_erp_nr, _category_erp_nr in pairs}
        category_erp_numbers = {category_erp_nr for _product_erp_nr, category_erp_nr in pairs}
        products_by_erp_nr = Product.objects.in_bulk(product_erp_numbers, field_name="erp_nr")
        categories_by_erp_nr = Category.objects.in_bulk(
            category_erp_numbers,
            field_name="legacy_erp_nr",
        )

        through_model = Product.categories.through
        desired_links: set[tuple[int, int]] = set()
        for product_erp_nr, category_erp_nr in pairs:
            product = products_by_erp_nr.get(product_erp_nr)
            category = categories_by_erp_nr.get(category_erp_nr)
            if product is None:
                missing_product_keys.add(product_erp_nr)
                continue
            if category is None:
                missing_category_keys.add(category_erp_nr)
                continue
            desired_links.add((product.pk, category.pk))

        product_ids = {product_id for product_id, _category_id in desired_links}
        category_ids = {category_id for _product_id, category_id in desired_links}
        existing_links = set()
        if product_ids and category_ids:
            existing_links = set(
                through_model.objects.filter(
                    product_id__in=product_ids,
                    category_id__in=category_ids,
                ).values_list("product_id", "category_id")
            )

        new_links = [
            through_model(product_id=product_id, category_id=category_id)
            for product_id, category_id in desired_links - existing_links
        ]
        if new_links:
            through_model.objects.bulk_create(new_links, ignore_conflicts=True)

        return {
            "source_rows": source_rows,
            "created": len(new_links),
            "existing": len(existing_links & desired_links),
            "missing_products": len(missing_product_keys),
            "missing_categories": len(missing_category_keys),
            "skipped": skipped_count,
        }

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
