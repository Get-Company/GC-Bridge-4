from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.services import BaseService
from hr.models import EmployeeProfile, MonthlyWorkSummary, SickLeave
from hr.services.holiday_service import HolidayService
from hr.services.leave_service import LeaveService
from hr.services.time_account_service import TimeAccountService
from hr.services.working_time_service import WorkingTimeService


class MonthlySummaryService(BaseService):
    model = MonthlyWorkSummary

    @staticmethod
    def build_balance_minutes(*, overtime_minutes: int, minus_minutes: int) -> int:
        return int(overtime_minutes or 0) + int(minus_minutes or 0)

    def _get_sick_minutes_for_month(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
        *,
        working_time_service: WorkingTimeService,
    ) -> int:
        month_days = working_time_service.get_days_in_month(year, month)
        if not month_days:
            return 0
        start_date = month_days[0]
        end_date = month_days[-1]
        total_minutes = 0

        sick_leaves = (
            SickLeave.objects.filter(employee=employee)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
            .order_by("start_date", "pk")
        )
        for sick_leave in sick_leaves:
            current_date = max(sick_leave.start_date, start_date)
            last_date = min(sick_leave.end_date, end_date)
            while current_date <= last_date:
                total_minutes += working_time_service.get_target_minutes_for_date(employee, current_date)
                current_date = current_date.fromordinal(current_date.toordinal() + 1)

        return total_minutes

    def calculate_monthly_summary(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
        *,
        save: bool = False,
    ) -> MonthlyWorkSummary:
        working_time_service = WorkingTimeService()
        leave_service = LeaveService()
        holiday_service = HolidayService()
        time_account_service = TimeAccountService()

        target_minutes = working_time_service.calculate_month_target_minutes(employee, year, month)
        vacation_minutes = leave_service.get_approved_leave_minutes_for_month(
            employee,
            year,
            month,
            working_time_service=working_time_service,
        )
        vacation_minutes += holiday_service.get_company_holiday_vacation_minutes_for_month(
            employee,
            year,
            month,
            working_time_service=working_time_service,
        )
        sick_minutes = self._get_sick_minutes_for_month(
            employee,
            year,
            month,
            working_time_service=working_time_service,
        )
        time_account_data = time_account_service.get_approved_minutes_for_month(employee, year, month)
        balance_minutes = self.build_balance_minutes(
            overtime_minutes=time_account_data["overtime_minutes"],
            minus_minutes=time_account_data["minus_minutes"],
        )

        summary = self.get_queryset().filter(employee=employee, year=year, month=month).first()
        if summary is None:
            summary = MonthlyWorkSummary(employee=employee, year=year, month=month)
        elif summary.locked and save:
            raise ValidationError("Die Monatsuebersicht ist abgeschlossen und kann nicht neu berechnet werden.")

        summary.target_minutes = target_minutes
        summary.vacation_minutes = vacation_minutes
        summary.sick_minutes = sick_minutes
        summary.overtime_minutes = time_account_data["overtime_minutes"]
        summary.minus_minutes = time_account_data["minus_minutes"]
        summary.balance_minutes = balance_minutes
        summary.calculated_at = timezone.now()

        if save:
            summary.full_clean()
            summary.save()
        return summary

    def recalculate_monthly_summary(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
    ) -> MonthlyWorkSummary:
        return self.calculate_monthly_summary(employee, year, month, save=True)

    def lock_monthly_summary(self, summary: MonthlyWorkSummary) -> MonthlyWorkSummary:
        summary.locked = True
        summary.calculated_at = timezone.now()
        summary.full_clean()
        summary.save(update_fields=["locked", "calculated_at", "updated_at"])
        return summary
