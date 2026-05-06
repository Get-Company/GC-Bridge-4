from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from core.services import BaseService
from hr.models import CompanyHoliday, EmployeeProfile, LeaveRequest, PublicHoliday, SickLeave, TimeAccountEntry
from hr.services.holiday_service import HolidayService
from hr.services.leave_service import LeaveService
from hr.services.time_account_service import TimeAccountService
from hr.services.working_time_service import WorkingTimeService


class WorkingTimeOverviewService(BaseService):
    model = EmployeeProfile
    METRIC_KEYS = (
        "scheduled_minutes",
        "planned_minutes",
        "vacation_minutes",
        "special_leave_minutes",
        "overtime_reduction_minutes",
        "sick_minutes",
        "public_holiday_minutes",
        "company_holiday_minutes",
        "bridge_day_minutes",
        "overtime_minutes",
        "minus_minutes",
    )
    UNIT_KEYS = (
        "scheduled_units",
        "planned_units",
        "vacation_units",
        "special_leave_units",
        "overtime_reduction_units",
        "sick_units",
        "public_holiday_units",
        "company_holiday_units",
        "bridge_day_units",
    )

    @staticmethod
    def _empty_row() -> dict[str, int | Decimal]:
        row: dict[str, int | Decimal] = {key: 0 for key in WorkingTimeOverviewService.METRIC_KEYS}
        row.update({key: Decimal("0.00") for key in WorkingTimeOverviewService.UNIT_KEYS})
        return row

    @staticmethod
    def _quantize_units(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.00"))

    @staticmethod
    def _daterange(start_date: date, end_date: date):
        current_date = start_date
        while current_date <= end_date:
            yield current_date
            current_date = current_date + timedelta(days=1)

    @staticmethod
    def _build_period_label(start_date: date, end_date: date) -> str:
        if start_date == end_date:
            return start_date.strftime("%d.%m.%Y")
        return f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}"

    def _build_leave_map(self, employee: EmployeeProfile, start_date: date, end_date: date) -> dict[date, dict[str, Decimal | str]]:
        leave_map: dict[date, dict[str, Decimal | str]] = {}
        leave_requests = LeaveService().get_approved_leave_requests(
            employee,
            start_date=start_date,
            end_date=end_date,
        )
        for leave_request in leave_requests:
            overlap_start = max(leave_request.start_date, start_date)
            overlap_end = min(leave_request.end_date, end_date)
            for current_date in self._daterange(overlap_start, overlap_end):
                fraction = Decimal("1.00")
                if current_date == leave_request.start_date and leave_request.half_day_start:
                    fraction -= Decimal("0.50")
                if current_date == leave_request.end_date and leave_request.half_day_end:
                    fraction -= Decimal("0.50")
                leave_map[current_date] = {
                    "leave_type": leave_request.leave_type,
                    "fraction": fraction,
                    "label": leave_request.get_leave_type_display(),
                }
        return leave_map

    def _build_sick_map(self, employee: EmployeeProfile, start_date: date, end_date: date) -> dict[date, str]:
        sick_map: dict[date, str] = {}
        sick_leaves = (
            SickLeave.objects.filter(employee=employee)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
            .order_by("start_date", "pk")
        )
        for sick_leave in sick_leaves:
            overlap_start = max(sick_leave.start_date, start_date)
            overlap_end = min(sick_leave.end_date, end_date)
            for current_date in self._daterange(overlap_start, overlap_end):
                sick_map[current_date] = "Krankheit"
        return sick_map

    def _build_public_holiday_map(self, employee: EmployeeProfile, start_date: date, end_date: date) -> dict[date, str]:
        calendar = HolidayService().get_employee_holiday_calendar(employee)
        if calendar is None:
            return {}
        public_holidays = (
            PublicHoliday.objects.filter(calendar=calendar, is_active=True, date__gte=start_date, date__lte=end_date)
            .order_by("date", "pk")
        )
        return {public_holiday.date: public_holiday.name for public_holiday in public_holidays}

    def _build_company_holiday_map(self, start_date: date, end_date: date) -> dict[date, CompanyHoliday]:
        company_holiday_map: dict[date, CompanyHoliday] = {}
        company_holidays = (
            CompanyHoliday.objects.filter(is_active=True, start_date__lte=end_date, end_date__gte=start_date)
            .order_by("start_date", "pk")
        )
        for company_holiday in company_holidays:
            overlap_start = max(company_holiday.start_date, start_date)
            overlap_end = min(company_holiday.end_date, end_date)
            for current_date in self._daterange(overlap_start, overlap_end):
                company_holiday_map[current_date] = company_holiday
        return company_holiday_map

    def _build_time_account_map(self, employee: EmployeeProfile, start_date: date, end_date: date) -> dict[date, dict[str, int]]:
        time_entries = (
            TimeAccountEntry.objects.filter(
                employee=employee,
                status=TimeAccountEntry.Status.APPROVED,
                date__gte=start_date,
                date__lte=end_date,
            )
            .order_by("date", "pk")
        )
        time_account_map: dict[date, dict[str, int]] = {}
        for entry in time_entries:
            row = time_account_map.setdefault(
                entry.date,
                {"overtime_minutes": 0, "minus_minutes": 0},
            )
            if entry.minutes > 0:
                row["overtime_minutes"] += int(entry.minutes)
            elif entry.minutes < 0:
                row["minus_minutes"] += int(entry.minutes)
        return time_account_map

    def _build_daily_row(
        self,
        *,
        employee: EmployeeProfile,
        target_date: date,
        working_time_service: WorkingTimeService,
        leave_map: dict[date, dict[str, Decimal | str]],
        sick_map: dict[date, str],
        public_holiday_map: dict[date, str],
        company_holiday_map: dict[date, CompanyHoliday],
        time_account_map: dict[date, dict[str, int]],
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "date": target_date,
            "period_label": self._build_period_label(target_date, target_date),
            "status_label": "Frei",
            "detail_label": "",
        }
        row.update(self._empty_row())

        scheduled_minutes = working_time_service.get_scheduled_target_minutes_for_date(employee, target_date)
        row["scheduled_minutes"] = scheduled_minutes
        row["overtime_minutes"] = time_account_map.get(target_date, {}).get("overtime_minutes", 0)
        row["minus_minutes"] = time_account_map.get(target_date, {}).get("minus_minutes", 0)

        if scheduled_minutes <= 0:
            return row

        scheduled_units = Decimal("1.00")
        row["scheduled_units"] = scheduled_units

        if target_date in company_holiday_map:
            company_holiday = company_holiday_map[target_date]
            row["status_label"] = "Brueckentag" if company_holiday.is_bridge_day else "Betriebsurlaub"
            row["detail_label"] = company_holiday.name
            if company_holiday.is_bridge_day:
                row["bridge_day_minutes"] = scheduled_minutes
                row["bridge_day_units"] = scheduled_units
            else:
                row["company_holiday_minutes"] = scheduled_minutes
                row["company_holiday_units"] = scheduled_units
            return row

        if target_date in public_holiday_map:
            row["status_label"] = "Feiertag"
            row["detail_label"] = str(public_holiday_map[target_date])
            row["public_holiday_minutes"] = scheduled_minutes
            row["public_holiday_units"] = scheduled_units
            return row

        if target_date in sick_map:
            row["status_label"] = "Krankheit"
            row["detail_label"] = sick_map[target_date]
            row["sick_minutes"] = scheduled_minutes
            row["sick_units"] = scheduled_units
            return row

        leave_entry = leave_map.get(target_date)
        if leave_entry is not None:
            leave_fraction = Decimal(str(leave_entry["fraction"]))
            leave_minutes = int((Decimal(scheduled_minutes) * leave_fraction).quantize(Decimal("1")))
            planned_minutes = scheduled_minutes - leave_minutes
            planned_units = scheduled_units - leave_fraction
            row["planned_minutes"] = planned_minutes
            row["planned_units"] = self._quantize_units(planned_units)
            row["status_label"] = str(leave_entry["label"])
            row["detail_label"] = str(leave_entry["label"])

            leave_type = leave_entry["leave_type"]
            if leave_type == LeaveRequest.LeaveType.VACATION:
                row["vacation_minutes"] = leave_minutes
                row["vacation_units"] = leave_fraction
            elif leave_type == LeaveRequest.LeaveType.SPECIAL_LEAVE:
                row["special_leave_minutes"] = leave_minutes
                row["special_leave_units"] = leave_fraction
            elif leave_type == LeaveRequest.LeaveType.OVERTIME_REDUCTION:
                row["overtime_reduction_minutes"] = leave_minutes
                row["overtime_reduction_units"] = leave_fraction
            return row

        row["status_label"] = "Arbeit"
        row["planned_minutes"] = scheduled_minutes
        row["planned_units"] = scheduled_units
        return row

    def _add_row_to_bucket(self, bucket: dict[str, object], row: dict[str, object]) -> None:
        for key in self.METRIC_KEYS + self.UNIT_KEYS:
            bucket[key] = bucket[key] + row[key]

    def _build_bucket(self, *, label: str, start_date: date, end_date: date) -> dict[str, object]:
        bucket: dict[str, object] = {
            "label": label,
            "start_date": start_date,
            "end_date": end_date,
            "period_label": self._build_period_label(start_date, end_date),
        }
        bucket.update(self._empty_row())
        return bucket

    def build_range_overview(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        working_time_service = WorkingTimeService()
        leave_map = self._build_leave_map(employee, start_date, end_date)
        sick_map = self._build_sick_map(employee, start_date, end_date)
        public_holiday_map = self._build_public_holiday_map(employee, start_date, end_date)
        company_holiday_map = self._build_company_holiday_map(start_date, end_date)
        time_account_map = self._build_time_account_map(employee, start_date, end_date)

        summary = self._build_bucket(
            label="Gesamt",
            start_date=start_date,
            end_date=end_date,
        )
        weekly_buckets: dict[tuple[int, int], dict[str, object]] = {}
        monthly_buckets: dict[tuple[int, int], dict[str, object]] = {}
        yearly_buckets: dict[int, dict[str, object]] = {}
        daily_rows: list[dict[str, object]] = []

        for target_date in self._daterange(start_date, end_date):
            row = self._build_daily_row(
                employee=employee,
                target_date=target_date,
                working_time_service=working_time_service,
                leave_map=leave_map,
                sick_map=sick_map,
                public_holiday_map=public_holiday_map,
                company_holiday_map=company_holiday_map,
                time_account_map=time_account_map,
            )
            daily_rows.append(row)
            self._add_row_to_bucket(summary, row)

            iso_year, iso_week, _ = target_date.isocalendar()
            week_key = (iso_year, iso_week)
            week_bucket = weekly_buckets.setdefault(
                week_key,
                self._build_bucket(
                    label=f"{iso_year} / KW {iso_week:02d}",
                    start_date=target_date,
                    end_date=target_date,
                ),
            )
            week_bucket["start_date"] = min(week_bucket["start_date"], target_date)
            week_bucket["end_date"] = max(week_bucket["end_date"], target_date)
            week_bucket["period_label"] = self._build_period_label(week_bucket["start_date"], week_bucket["end_date"])
            self._add_row_to_bucket(week_bucket, row)

            month_key = (target_date.year, target_date.month)
            month_bucket = monthly_buckets.setdefault(
                month_key,
                self._build_bucket(
                    label=f"{target_date:%m/%Y}",
                    start_date=target_date,
                    end_date=target_date,
                ),
            )
            month_bucket["start_date"] = min(month_bucket["start_date"], target_date)
            month_bucket["end_date"] = max(month_bucket["end_date"], target_date)
            month_bucket["period_label"] = self._build_period_label(month_bucket["start_date"], month_bucket["end_date"])
            self._add_row_to_bucket(month_bucket, row)

            year_bucket = yearly_buckets.setdefault(
                target_date.year,
                self._build_bucket(
                    label=str(target_date.year),
                    start_date=target_date,
                    end_date=target_date,
                ),
            )
            year_bucket["start_date"] = min(year_bucket["start_date"], target_date)
            year_bucket["end_date"] = max(year_bucket["end_date"], target_date)
            year_bucket["period_label"] = self._build_period_label(year_bucket["start_date"], year_bucket["end_date"])
            self._add_row_to_bucket(year_bucket, row)

        return {
            "summary": summary,
            "daily_rows": daily_rows,
            "weekly_rows": sorted(weekly_buckets.values(), key=lambda row: row["start_date"]),
            "monthly_rows": sorted(monthly_buckets.values(), key=lambda row: row["start_date"]),
            "yearly_rows": sorted(yearly_buckets.values(), key=lambda row: row["start_date"]),
            "time_account_balance_minutes": TimeAccountService().get_time_account_balance(
                employee,
                until_date=end_date,
            ),
        }
