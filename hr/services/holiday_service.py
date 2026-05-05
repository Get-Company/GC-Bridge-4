from __future__ import annotations

from datetime import date

from core.services import BaseService
from hr.models import CompanyHoliday, EmployeeProfile, HolidayCalendar, PublicHoliday


class HolidayService(BaseService):
    model = PublicHoliday

    @staticmethod
    def overlaps(*, start_date: date, end_date: date, other_start_date: date, other_end_date: date) -> bool:
        return start_date <= other_end_date and other_start_date <= end_date

    def get_default_holiday_calendar(self) -> HolidayCalendar | None:
        return HolidayCalendar.objects.filter(is_active=True, is_default=True).order_by("name", "pk").first()

    def get_employee_holiday_calendar(self, employee: EmployeeProfile) -> HolidayCalendar | None:
        return employee.holiday_calendar if employee.holiday_calendar_id else self.get_default_holiday_calendar()

    def get_public_holiday_for_employee(self, employee: EmployeeProfile, target_date: date) -> PublicHoliday | None:
        calendar = self.get_employee_holiday_calendar(employee)
        if calendar is None:
            return None
        return (
            PublicHoliday.objects.filter(calendar=calendar, is_active=True, date=target_date)
            .order_by("name", "pk")
            .first()
        )

    def get_company_holiday_for_date(self, target_date: date) -> CompanyHoliday | None:
        return (
            CompanyHoliday.objects.filter(is_active=True, start_date__lte=target_date, end_date__gte=target_date)
            .order_by("start_date", "pk")
            .first()
        )

    def has_company_holiday_overlap(self, *, start_date: date, end_date: date) -> bool:
        return CompanyHoliday.objects.filter(
            is_active=True,
            start_date__lte=end_date,
            end_date__gte=start_date,
        ).exists()

    def is_public_holiday(self, employee: EmployeeProfile, target_date: date) -> bool:
        return self.get_public_holiday_for_employee(employee, target_date) is not None

    def is_company_holiday(self, target_date: date) -> bool:
        return self.get_company_holiday_for_date(target_date) is not None

    def is_non_working_holiday(self, employee: EmployeeProfile, target_date: date) -> bool:
        return self.is_public_holiday(employee, target_date) or self.is_company_holiday(target_date)

    def get_company_holiday_vacation_minutes_for_month(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
        *,
        working_time_service,
    ) -> int:
        month_days = working_time_service.get_days_in_month(year, month)
        if not month_days:
            return 0

        start_date = month_days[0]
        end_date = month_days[-1]
        total_minutes = 0
        company_holidays = (
            CompanyHoliday.objects.filter(
                is_active=True,
                counts_as_vacation=True,
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
            .order_by("start_date", "pk")
        )
        for company_holiday in company_holidays:
            current_date = max(company_holiday.start_date, start_date)
            last_date = min(company_holiday.end_date, end_date)
            while current_date <= last_date:
                total_minutes += working_time_service.get_scheduled_target_minutes_for_date(employee, current_date)
                current_date = current_date.fromordinal(current_date.toordinal() + 1)
        return total_minutes
