from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from products.models import Price, PriceHistory, Product
from shopware.models import ShopwareSettings


@dataclass
class ParsedHistoryRow:
    row_number: int
    product: Product
    sales_channel: ShopwareSettings
    effective_at: datetime
    price: Decimal
    rebate_quantity: int | None
    rebate_price: Decimal | None
    special_percentage: Decimal | None
    special_price: Decimal | None
    special_start_date: datetime | None
    special_end_date: datetime | None


class Command(BaseCommand):
    help = (
        "Importiert historische Preisstaende aus CSV in PriceHistory. "
        "Validierungsfehler werden pro Zeile protokolliert und brechen den Gesamtlauf nicht ab."
    )

    REQUIRED_COLUMNS = ("erp_nr", "gueltig_ab", "preis")
    OPTIONAL_COLUMNS = (
        "sales_channel",
        "rebate_quantity",
        "rebate_price",
        "special_percentage",
        "special_price",
        "special_start_date",
        "special_end_date",
        "gueltig_bis",
        "quelle",
        "kommentar",
    )
    DATETIME_FORMATS = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            help="Pfad zur CSV-Datei mit historischen Preisstaenden.",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Schreibt gueltige Zeilen in die Datenbank. Ohne diesen Schalter laeuft nur die Validierung.",
        )
        parser.add_argument(
            "--delimiter",
            default="",
            help="Optionales CSV-Trennzeichen. Wenn leer, wird automatisch erkannt.",
        )
        parser.add_argument(
            "--default-sales-channel",
            default="",
            help="Optionaler Fallback-Sales-Channel-Name. Sonst wird der aktive Standardkanal verwendet.",
        )
        parser.add_argument(
            "--error-report",
            default="tmp/import_price_history_errors.csv",
            help="Pfad fuer den CSV-Fehlerreport. Default: tmp/import_price_history_errors.csv",
        )
        parser.add_argument(
            "--create-missing-prices",
            action="store_true",
            help=(
                "Legt fehlende aktuelle Price-Zeilen fuer Produkt + Verkaufskanal an. "
                "Standard ist AUS, damit bestehende Live-Preise nicht versehentlich geaendert werden."
            ),
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"]).resolve()
        if not csv_path.exists():
            raise CommandError(f"CSV-Datei nicht gefunden: {csv_path}")

        error_report_path = Path(options["error_report"]).resolve()
        error_report_path.parent.mkdir(parents=True, exist_ok=True)

        default_sales_channel = self._get_default_sales_channel(options.get("default_sales_channel", ""))
        delimiter = options.get("delimiter", "").strip()
        commit = bool(options.get("commit"))
        create_missing_prices = bool(options.get("create_missing_prices"))

        mode_label = "COMMIT" if commit else "DRY-RUN"
        self.stdout.write(f"Importmodus: {mode_label}")
        self.stdout.write(f"CSV: {csv_path}")
        self.stdout.write(f"Fehlerreport: {error_report_path}")

        rows = list(self._read_csv(csv_path=csv_path, delimiter=delimiter))
        if not rows:
            raise CommandError("Die CSV-Datei ist leer.")

        headers = tuple((rows[0].keys() if rows else []))
        self._validate_headers(headers=headers)

        imported = 0
        validated = 0
        skipped = 0
        errors: list[dict[str, str]] = []

        for row_number, row in enumerate(rows, start=2):
            try:
                parsed = self._parse_row(
                    row_number=row_number,
                    row=row,
                    default_sales_channel=default_sales_channel,
                )
            except CommandError as exc:
                skipped += 1
                errors.append(self._build_error_row(row_number=row_number, row=row, message=str(exc)))
                continue

            validated += 1
            if not commit:
                continue

            try:
                with transaction.atomic():
                    self._import_row(parsed=parsed, create_missing_prices=create_missing_prices)
            except CommandError as exc:
                skipped += 1
                errors.append(self._build_error_row(row_number=row_number, row=row, message=str(exc)))
                continue

            imported += 1

        self._write_error_report(error_report_path=error_report_path, errors=errors)

        self.stdout.write(
            self.style.SUCCESS(
                "Preisverlauf verarbeitet: "
                f"validiert={validated}, importiert={imported}, fehlerhaft/uebersprungen={skipped}"
            )
        )
        if errors:
            self.stdout.write(self.style.WARNING(f"Fehlerreport geschrieben: {error_report_path}"))

    def _read_csv(self, *, csv_path: Path, delimiter: str):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            sample = csv_file.read(4096)
            csv_file.seek(0)
            resolved_delimiter = delimiter or self._detect_delimiter(sample)
            reader = csv.DictReader(csv_file, delimiter=resolved_delimiter)
            for row in reader:
                yield {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}

    @staticmethod
    def _detect_delimiter(sample: str) -> str:
        if ";" in sample:
            return ";"
        if "\t" in sample:
            return "\t"
        return ","

    def _validate_headers(self, *, headers: tuple[str, ...]) -> None:
        missing = [column for column in self.REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise CommandError(f"Pflichtspalten fehlen: {', '.join(missing)}")

    def _get_default_sales_channel(self, configured_name: str) -> ShopwareSettings:
        configured_name = configured_name.strip()
        if configured_name:
            sales_channel = ShopwareSettings.objects.filter(name=configured_name, is_active=True).first()
            if sales_channel is None:
                raise CommandError(f"Default-Sales-Channel nicht gefunden oder inaktiv: {configured_name}")
            return sales_channel

        sales_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).order_by("pk").first()
        if sales_channel is None:
            raise CommandError("Kein aktiver Standard-Verkaufskanal konfiguriert.")
        return sales_channel

    def _parse_row(
        self,
        *,
        row_number: int,
        row: dict[str, str],
        default_sales_channel: ShopwareSettings,
    ) -> ParsedHistoryRow:
        erp_nr = row.get("erp_nr", "").strip()
        if not erp_nr:
            raise CommandError("erp_nr fehlt.")

        product = Product.objects.filter(erp_nr=erp_nr).first()
        if product is None:
            raise CommandError(f"Produkt mit ERP-Nr. '{erp_nr}' nicht gefunden.")

        sales_channel = self._resolve_sales_channel(
            value=row.get("sales_channel", ""),
            default_sales_channel=default_sales_channel,
        )
        effective_at = self._parse_datetime(
            value=row.get("gueltig_ab", ""),
            field_name="gueltig_ab",
        )
        price = self._parse_decimal(row.get("preis", ""), field_name="preis", required=True)
        rebate_quantity = self._parse_int(row.get("rebate_quantity", ""), field_name="rebate_quantity")
        rebate_price = self._parse_decimal(row.get("rebate_price", ""), field_name="rebate_price")
        special_percentage = self._parse_decimal(
            row.get("special_percentage", ""),
            field_name="special_percentage",
        )
        special_price = self._parse_decimal(row.get("special_price", ""), field_name="special_price")
        special_start_date = self._parse_datetime(
            value=row.get("special_start_date", ""),
            field_name="special_start_date",
            required=False,
        )
        special_end_date = self._parse_datetime(
            value=row.get("special_end_date", ""),
            field_name="special_end_date",
            required=False,
        )

        if special_start_date and special_end_date and special_end_date < special_start_date:
            raise CommandError("special_end_date liegt vor special_start_date.")

        if special_price is None and special_percentage is not None:
            special_price = Price._round_up_5ct(
                price * (Decimal("100") - special_percentage) / Decimal("100")
            ).quantize(Decimal("0.01"))

        return ParsedHistoryRow(
            row_number=row_number,
            product=product,
            sales_channel=sales_channel,
            effective_at=effective_at,
            price=price,
            rebate_quantity=rebate_quantity,
            rebate_price=rebate_price,
            special_percentage=special_percentage,
            special_price=special_price,
            special_start_date=special_start_date,
            special_end_date=special_end_date,
        )

    def _resolve_sales_channel(
        self,
        *,
        value: str,
        default_sales_channel: ShopwareSettings,
    ) -> ShopwareSettings:
        value = value.strip()
        if not value:
            return default_sales_channel
        sales_channel = ShopwareSettings.objects.filter(name=value, is_active=True).first()
        if sales_channel is None:
            raise CommandError(f"Verkaufskanal '{value}' nicht gefunden oder inaktiv.")
        return sales_channel

    def _parse_decimal(self, value: str, *, field_name: str, required: bool = False) -> Decimal | None:
        value = value.strip()
        if not value:
            if required:
                raise CommandError(f"{field_name} fehlt.")
            return None
        normalized = value.replace("€", "").replace(" ", "")
        if "," in normalized and "." in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        elif "," in normalized:
            normalized = normalized.replace(",", ".")
        try:
            return Decimal(normalized).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise CommandError(f"{field_name} ist kein gueltiger Dezimalwert: {value}")

    def _parse_int(self, value: str, *, field_name: str) -> int | None:
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            raise CommandError(f"{field_name} ist keine gueltige Ganzzahl: {value}")

    def _parse_datetime(self, *, value: str, field_name: str, required: bool = True) -> datetime | None:
        value = value.strip()
        if not value:
            if required:
                raise CommandError(f"{field_name} fehlt.")
            return None

        for fmt in self.DATETIME_FORMATS:
            try:
                parsed = datetime.strptime(value, fmt)
            except ValueError:
                continue

            if "H" not in fmt:
                parsed = datetime.combine(parsed.date(), time.min)
            if timezone.is_naive(parsed):
                return timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed

        raise CommandError(f"{field_name} hat ein ungueltiges Datumsformat: {value}")

    def _import_row(self, *, parsed: ParsedHistoryRow, create_missing_prices: bool) -> None:
        price_entry = Price.objects.filter(
            product=parsed.product,
            sales_channel=parsed.sales_channel,
        ).first()
        if price_entry is None:
            if not create_missing_prices:
                raise CommandError(
                    "Keine aktuelle Price-Zeile fuer Produkt "
                    f"{parsed.product.erp_nr} / {parsed.sales_channel.name} gefunden."
                )
            price_entry = Price.objects.create(
                product=parsed.product,
                sales_channel=parsed.sales_channel,
                price=parsed.price,
                rebate_quantity=parsed.rebate_quantity,
                rebate_price=parsed.rebate_price,
                special_percentage=parsed.special_percentage,
                special_price=parsed.special_price,
                special_start_date=parsed.special_start_date,
                special_end_date=parsed.special_end_date,
            )

        duplicate_exists = PriceHistory.objects.filter(
            price_entry=price_entry,
            created_at=parsed.effective_at,
        ).exists()
        if duplicate_exists:
            raise CommandError(
                f"Es existiert bereits ein Preisverlauf fuer {parsed.product.erp_nr} am {parsed.effective_at.isoformat()}."
            )

        history_entry = PriceHistory.objects.create(
            price_entry=price_entry,
            change_type=PriceHistory.ChangeType.UPDATED,
            changed_fields="imported_history",
            price=parsed.price,
            rebate_quantity=parsed.rebate_quantity,
            rebate_price=parsed.rebate_price,
            special_percentage=parsed.special_percentage,
            special_price=parsed.special_price,
            special_start_date=parsed.special_start_date,
            special_end_date=parsed.special_end_date,
        )
        PriceHistory.objects.filter(pk=history_entry.pk).update(
            created_at=parsed.effective_at,
            updated_at=parsed.effective_at,
        )

    @staticmethod
    def _build_error_row(*, row_number: int, row: dict[str, str], message: str) -> dict[str, str]:
        return {
            "row_number": str(row_number),
            "error": message,
            **row,
        }

    def _write_error_report(self, *, error_report_path: Path, errors: list[dict[str, str]]) -> None:
        if not errors:
            if error_report_path.exists():
                error_report_path.unlink()
            return

        fieldnames = sorted({key for error in errors for key in error.keys()}, key=lambda item: (item != "row_number", item))
        with error_report_path.open("w", encoding="utf-8", newline="") as report_file:
            writer = csv.DictWriter(report_file, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(errors)
