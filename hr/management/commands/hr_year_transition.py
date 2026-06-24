from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.management.base import MonitoredBaseCommand

from hr.models import EmployeeProfile, VacationEntitlement
from hr.services.leave_service import LeaveService


class Command(MonitoredBaseCommand):
    help = "Jahreswechsel: legt VacationEntitlement fuer das Zieljahr an und uebertraegt Resturlaub."

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="Zieljahr fuer den Jahreswechsel (Standard: naechstes Jahr).",
        )
        parser.add_argument(
            "--max-carryover",
            type=float,
            default=None,
            help="Maximaler Resturlaub-Uebertrag in Tagen (Standard: kein Limit).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur anzeigen, keine Daten anlegen.",
        )

    def handle(self, *args, **options):
        target_year: int = options["year"] or date.today().year + 1
        max_carryover: Decimal | None = (
            Decimal(str(options["max_carryover"])) if options["max_carryover"] is not None else None
        )
        dry_run: bool = options["dry_run"]
        prev_year = target_year - 1

        prefix = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(f"{prefix}Jahreswechsel {prev_year} → {target_year}")
        if max_carryover is not None:
            self.stdout.write(f"  Max. Uebertrag: {max_carryover:.2f} Tage")

        leave_service = LeaveService()
        employees = (
            EmployeeProfile.objects.filter(is_active_employee=True)
            .select_related("user")
            .order_by("user__last_name", "user__first_name")
        )

        created = 0
        skipped = 0

        for employee in employees:
            if VacationEntitlement.objects.filter(employee=employee, year=target_year).exists():
                self.stdout.write(f"  SKIP  {employee}: Eintrag fuer {target_year} existiert bereits.")
                skipped += 1
                continue

            remaining = leave_service.get_remaining_vacation_days_for_year(employee, prev_year)
            remaining = max(Decimal("0.00"), remaining)
            if max_carryover is not None:
                remaining = min(remaining, max_carryover)
            remaining = remaining.quantize(Decimal("0.00"))

            carryover_expires = date(target_year, 3, 31)
            note = f"Jahreswechsel {prev_year} → {target_year}: Resturlaub {remaining} Tage, verfaellt {carryover_expires}."

            self.stdout.write(
                f"  {'CREATE' if not dry_run else 'WOULD CREATE'}  {employee}: "
                f"Basis={employee.vacation_days_per_year}, Uebertrag={remaining}, "
                f"verfaellt={carryover_expires}"
            )

            if not dry_run:
                VacationEntitlement.objects.create(
                    employee=employee,
                    year=target_year,
                    base_days=Decimal(str(employee.vacation_days_per_year)),
                    carryover_days=remaining,
                    carryover_expires_on=carryover_expires,
                    note=note,
                )
                created += 1
            else:
                created += 1

        self.stdout.write(f"\n{prefix}Fertig: {created} angelegt, {skipped} uebersprungen.")
