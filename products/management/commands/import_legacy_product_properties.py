from __future__ import annotations

import sqlite3
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from products.models import Product, ProductProperty, PropertyGroup, PropertyValue


class Command(BaseCommand):
    help = "Importiert Legacy-Produktattribute aus SQLite oder direkt aus database.sql."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="Optionale ERP-Nummern. Wenn leer, werden alle Legacy-Attribute importiert.",
        )
        parser.add_argument(
            "--sqlite-path",
            default="tmp/legacy_v3.sqlite3",
            help="Pfad zur Legacy-SQLite-Datei. Default: tmp/legacy_v3.sqlite3",
        )
        parser.add_argument(
            "--dump-path",
            default="",
            help="Optionaler Pfad zur Legacy-MySQL-Dump-Datei (database.sql). Wenn gesetzt, wird daraus bei Bedarf SQLite erzeugt.",
        )
        parser.add_argument(
            "--rebuild-sqlite",
            action="store_true",
            help="Erzeugt die Legacy-SQLite-Datei aus --dump-path neu, auch wenn sie bereits existiert.",
        )
        parser.add_argument(
            "--replace-product-properties",
            action="store_true",
            help="Ersetzt vorhandene Produktattribut-Zuordnungen fuer die betroffenen Produkte vor dem Import.",
        )

    def handle(self, *args, **options):
        sqlite_path = self._resolve_sqlite_path(
            sqlite_path_value=options["sqlite_path"],
            dump_path_value=options.get("dump_path", ""),
            rebuild_sqlite=options.get("rebuild_sqlite", False),
        )
        erp_nrs = [erp_nr.strip() for erp_nr in options.get("erp_nrs") or [] if erp_nr.strip()]
        replace_product_properties = options.get("replace_product_properties", False)

        connection = sqlite3.connect(sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = list(self._load_rows(connection=connection, erp_nrs=erp_nrs))
        finally:
            connection.close()

        if not rows:
            self.stdout.write("Keine passenden Legacy-Produktattribute gefunden.")
            return

        current_products_by_erp = {
            product.erp_nr: product
            for product in Product.objects.filter(erp_nr__in=sorted({str(row["erp_nr"] or "").strip() for row in rows}))
        }
        touched_product_ids = set()
        created_groups = 0
        updated_groups = 0
        created_values = 0
        updated_values = 0
        created_links = 0
        existing_links = 0
        skipped_rows = 0

        with transaction.atomic():
            if replace_product_properties:
                product_ids_to_reset = [
                    product.id
                    for product in current_products_by_erp.values()
                ]
                if product_ids_to_reset:
                    ProductProperty.objects.filter(product_id__in=product_ids_to_reset).delete()

            for row in rows:
                erp_nr = str(row["erp_nr"] or "").strip()
                current_product = current_products_by_erp.get(erp_nr)
                if current_product is None:
                    skipped_rows += 1
                    continue

                group_defaults = self._build_name_defaults(row=row, field_prefix="group")
                group, group_created = PropertyGroup.objects.update_or_create(
                    external_key=f"legacy-property-group:{row['group_id']}",
                    defaults=group_defaults,
                )
                if group_created:
                    created_groups += 1
                else:
                    updated_groups += 1

                value_defaults = self._build_name_defaults(row=row, field_prefix="value")
                value_defaults["group"] = group
                value, value_created = PropertyValue.objects.update_or_create(
                    external_key=f"legacy-property-value:{row['value_id']}",
                    defaults=value_defaults,
                )
                if value_created:
                    created_values += 1
                else:
                    updated_values += 1

                _, link_created = ProductProperty.objects.update_or_create(
                    product=current_product,
                    value=value,
                    defaults={
                        "external_key": f"legacy-product-property:{row['product_property_id']}",
                    },
                )
                if link_created:
                    created_links += 1
                else:
                    existing_links += 1
                touched_product_ids.add(current_product.id)

        self.stdout.write(
            self.style.SUCCESS(
                "Legacy Produktattribute importiert: "
                f"groups(created={created_groups}, updated={updated_groups}), "
                f"values(created={created_values}, updated={updated_values}), "
                f"links(created={created_links}, existing={existing_links}), "
                f"products={len(touched_product_ids)}, skipped={skipped_rows}"
            )
        )

    def _resolve_sqlite_path(self, *, sqlite_path_value: str, dump_path_value: str, rebuild_sqlite: bool) -> Path:
        sqlite_path = Path(sqlite_path_value).resolve()
        dump_path = Path(dump_path_value).resolve() if dump_path_value else None

        if dump_path:
            if not dump_path.exists():
                raise CommandError(f"Legacy Dump-Datei nicht gefunden: {dump_path}")
            if rebuild_sqlite or not sqlite_path.exists():
                call_command("legacy_dump_to_sqlite", str(dump_path), str(sqlite_path), overwrite=True)

        if not sqlite_path.exists():
            raise CommandError(
                f"Legacy SQLite-Datei nicht gefunden: {sqlite_path}. "
                "Nutze --dump-path database.sql oder uebergib einen gueltigen --sqlite-path."
            )

        return sqlite_path

    def _load_rows(self, *, connection: sqlite3.Connection, erp_nrs: list[str]):
        base_sql = """
            SELECT
                pp.id AS product_property_id,
                p.erp_nr,
                pg.id AS group_id,
                pg.name AS group_name,
                pg.name_de AS group_name_de,
                pg.name_en AS group_name_en,
                pv.id AS value_id,
                pv.name AS value_name,
                pv.name_de AS value_name_de,
                pv.name_en AS value_name_en
            FROM products_productproperty AS pp
            INNER JOIN products_product AS p ON p.id = pp.product_id
            INNER JOIN products_propertyvalue AS pv ON pv.id = pp.value_id
            INNER JOIN products_propertygroup AS pg ON pg.id = pv.group_id
        """
        params: list[str] = []
        if erp_nrs:
            placeholders = ",".join("?" for _ in erp_nrs)
            base_sql += f" WHERE p.erp_nr IN ({placeholders})"
            params.extend(erp_nrs)
        base_sql += " ORDER BY p.erp_nr, pg.id, pv.id"
        yield from connection.execute(base_sql, params)

    @staticmethod
    def _build_name_defaults(*, row: sqlite3.Row, field_prefix: str) -> dict[str, str]:
        base_name = str(
            row[f"{field_prefix}_name_de"]
            or row[f"{field_prefix}_name"]
            or row[f"{field_prefix}_name_en"]
            or ""
        ).strip()
        name_de = str(row[f"{field_prefix}_name_de"] or base_name or "").strip()
        name_en = str(row[f"{field_prefix}_name_en"] or base_name or "").strip()
        defaults = {
            "name": base_name,
            "name_de": name_de,
            "name_en": name_en,
        }
        return defaults
