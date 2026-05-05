from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.db.models import Q

from core.services import BaseService
from hr.models import EmployeeProfile, EmployeeWorkSchedule, WorkSchedule
from hr.services.holiday_service import HolidayService


class WorkingTimeService(BaseService):
    model = EmployeeWorkSchedule

    @staticmethod
    def get_days_in_month(year: int, month: int) -> list[date]:
        day_count = monthrange(year, month)[1]
        return [date(year, month, day) for day in range(1, day_count + 1)]

    def get_employee_schedule_assignment_for_date(
        self,
        employee: EmployeeProfile,
        target_date: date,
    ) -> EmployeeWorkSchedule | None:
        return (
            self.get_queryset()
            .filter(employee=employee, valid_from__lte=target_date)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=target_date))
            .select_related("schedule")
            .order_by("-valid_from", "-pk")
            .first()
        )

    def get_employee_schedule_for_date(
        self,
        employee: EmployeeProfile,
        target_date: date,
    ) -> WorkSchedule | None:
        assignment = self.get_employee_schedule_assignment_for_date(employee, target_date)
        return assignment.schedule if assignment else None

    def get_target_minutes_for_date(
        self,
        employee: EmployeeProfile,
        target_date: date,
    ) -> int:
        if employee.start_date and target_date < employee.start_date:
            return 0
        if employee.end_date and target_date > employee.end_date:
            return 0

        base_target_minutes = self.get_scheduled_target_minutes_for_date(employee, target_date)
        if base_target_minutes <= 0:
            return 0
        if HolidayService().is_non_working_holiday(employee, target_date):
            return 0
        return base_target_minutes

    def get_scheduled_target_minutes_for_date(
        self,
        employee: EmployeeProfile,
        target_date: date,
    ) -> int:
        if employee.start_date and target_date < employee.start_date:
            return 0
        if employee.end_date and target_date > employee.end_date:
            return 0

        schedule = self.get_employee_schedule_for_date(employee, target_date)
        if schedule is None:
            return 0

        schedule_day = schedule.days.filter(weekday=target_date.weekday()).first()
        if schedule_day is None or not schedule_day.is_working_day:
            return 0
        return int(schedule_day.target_minutes or 0)

    def calculate_month_target_minutes(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
    ) -> int:
        return sum(self.get_target_minutes_for_date(employee, day) for day in self.get_days_in_month(year, month))
