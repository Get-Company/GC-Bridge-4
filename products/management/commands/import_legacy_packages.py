from __future__ import annotations

import sqlite3
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.management.base import MonitoredBaseCommand
from products.models import Package, Product


class Command(MonitoredBaseCommand):
    help = "Importiert Pakete, Paket-GTINs und Mabox-Zuordnungen aus einem Legacy-v3-Dump."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite-path",
            default="tmp/legacy_v3.sqlite3",
            help="Pfad zur konvertierten Legacy-SQLite-Datei.",
        )
        parser.add_argument(
            "--dump-path",
            default="database.sql",
            help="Pfad zum Legacy-MySQL-Dump, falls die SQLite-Datei erzeugt werden soll.",
        )
        parser.add_argument(
            "--rebuild-sqlite",
            action="store_true",
            help="Erzeugt die SQLite-Datei vor dem Import neu aus --dump-path.",
        )
        parser.add_argument(
            "--mabox-sub-marketplace-id",
            type=int,
            default=5,
            help="Legacy-ID des Mabox-Sub-Marktplatzes. Default: 5",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Prüft Zuordnungen und meldet das Ergebnis, ohne Pakete zu speichern.",
        )

    def handle(self, *args, **options):
        sqlite_path = self._resolve_sqlite_path(
            sqlite_path_value=options["sqlite_path"],
            dump_path_value=options["dump_path"],
            rebuild_sqlite=options["rebuild_sqlite"],
        )
        connection = sqlite3.connect(sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            self._validate_tables(connection)
            rows = list(
                connection.execute(
                    """
                    SELECT
                        packages.id AS legacy_id,
                        packages.package_nr,
                        packages.quantity,
                        packages.created_at,
                        packages.updated_at,
                        products.erp_nr AS product_erp_nr,
                        COALESCE(gtins.code, '') AS gtin,
                        EXISTS(
                            SELECT 1
                            FROM products_packagesubmarketplace package_channels
                            WHERE package_channels.package_id = packages.id
                              AND package_channels.sub_marketplace_id = ?
                        ) AS mabox_enabled
                    FROM products_package packages
                    INNER JOIN products_product products
                        ON products.id = packages.product_id
                    LEFT JOIN products_gtin gtins
                        ON gtins.package_id = packages.id
                    ORDER BY products.erp_nr, packages.quantity, packages.package_nr
                    """,
                    (options["mabox_sub_marketplace_id"],),
                )
            )
        finally:
            connection.close()

        product_numbers = {
            str(row["product_erp_nr"] or "").strip()
            for row in rows
            if str(row["product_erp_nr"] or "").strip()
        }
        products_by_number = Product.objects.in_bulk(product_numbers, field_name="erp_nr")
        missing_products = sorted(product_numbers - set(products_by_number))
        valid_rows = [
            row
            for row in rows
            if self._is_valid_row(row) and str(row["product_erp_nr"]).strip() in products_by_number
        ]

        if options["dry_run"]:
            valid_package_numbers = [str(row["package_nr"]).strip() for row in valid_rows]
            existing_package_numbers = set(
                Package.objects.filter(package_nr__in=valid_package_numbers).values_list("package_nr", flat=True)
            )
            self._write_summary(
                source_count=len(rows),
                created_count=len(valid_package_numbers) - len(existing_package_numbers),
                updated_count=len(existing_package_numbers),
                skipped_count=len(rows) - len(valid_rows),
                missing_products=missing_products,
                dry_run=True,
            )
            return

        created_count = 0
        updated_count = 0
        with transaction.atomic():
            for row in valid_rows:
                product = products_by_number[str(row["product_erp_nr"]).strip()]
                package, created = Package.objects.update_or_create(
                    package_nr=str(row["package_nr"]).strip(),
                    defaults={
                        "product": product,
                        "quantity": int(row["quantity"]),
                        "gtin": str(row["gtin"] or "").strip(),
                        "legacy_id": int(row["legacy_id"]),
                        "is_active": True,
                        "mabox_enabled": bool(row["mabox_enabled"]),
                    },
                )
                created_count += int(created)
                updated_count += int(not created)
                self._restore_timestamps(package=package, row=row)

        self._write_summary(
            source_count=len(rows),
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=len(rows) - len(valid_rows),
            missing_products=missing_products,
            dry_run=False,
        )

    @staticmethod
    def _is_valid_row(row: sqlite3.Row) -> bool:
        package_nr = str(row["package_nr"] or "").strip()
        try:
            quantity = int(row["quantity"])
        except (TypeError, ValueError):
            return False
        return bool(package_nr and quantity >= 1)

    @staticmethod
    def _validate_tables(connection: sqlite3.Connection) -> None:
        required = {
            "products_package",
            "products_product",
            "products_gtin",
            "products_packagesubmarketplace",
        }
        placeholders = ", ".join("?" for _ in required)
        existing = {
            row[0]
            for row in connection.execute(
                f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
                tuple(required),
            )
        }
        missing = sorted(required - existing)
        if missing:
            raise CommandError(f"Legacy-Tabellen fehlen: {', '.join(missing)}")

    @staticmethod
    def _resolve_sqlite_path(*, sqlite_path_value: str, dump_path_value: str, rebuild_sqlite: bool) -> Path:
        sqlite_path = Path(sqlite_path_value).resolve()
        dump_path = Path(dump_path_value).resolve()
        if rebuild_sqlite or not sqlite_path.exists():
            if not dump_path.exists():
                raise CommandError(f"Legacy-Dump nicht gefunden: {dump_path}")
            if dump_path.stat().st_size == 0:
                raise CommandError(f"Legacy-Dump ist leer: {dump_path}")
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            call_command("legacy_dump_to_sqlite", str(dump_path), str(sqlite_path), overwrite=True)
        if not sqlite_path.exists():
            raise CommandError(f"Legacy-SQLite-Datei nicht gefunden: {sqlite_path}")
        return sqlite_path

    @classmethod
    def _restore_timestamps(cls, *, package: Package, row: sqlite3.Row) -> None:
        created_at = cls._parse_datetime(row["created_at"])
        updated_at = cls._parse_datetime(row["updated_at"])
        values = {}
        if created_at is not None:
            values["created_at"] = created_at
        if updated_at is not None:
            values["updated_at"] = updated_at
        if values:
            Package.objects.filter(pk=package.pk).update(**values)

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is not None and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _write_summary(
        self,
        *,
        source_count: int,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        missing_products: list[str],
        dry_run: bool,
    ) -> None:
        mode = "Trockenlauf" if dry_run else "Import"
        message = (
            f"{mode} Legacy-Pakete: source={source_count}, created={created_count}, "
            f"updated={updated_count}, skipped={skipped_count}, "
            f"missing_products={len(missing_products)}"
        )
        self.stdout.write(self.style.WARNING(message) if dry_run else self.style.SUCCESS(message))
        if missing_products:
            preview = ", ".join(missing_products[:25])
            suffix = " …" if len(missing_products) > 25 else ""
            self.stdout.write(f"Nicht gefundene Produkte: {preview}{suffix}")
