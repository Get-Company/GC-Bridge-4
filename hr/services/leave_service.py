from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from core.services import BaseService
from hr.models import CompanyHoliday, EmployeeProfile, LeaveRequest, SickLeave, VacationEntitlement
from hr.services.holiday_service import HolidayService
from hr.services.working_time_service import WorkingTimeService


class LeaveService(BaseService):
    model = LeaveRequest
    STATUS_TRANSITIONS = {
        LeaveRequest.Status.REQUESTED: {
            LeaveRequest.Status.APPROVED,
            LeaveRequest.Status.REJECTED,
            LeaveRequest.Status.CANCELLED,
        },
        LeaveRequest.Status.APPROVED: {LeaveRequest.Status.CANCELLED},
        LeaveRequest.Status.REJECTED: set(),
        LeaveRequest.Status.CANCELLED: set(),
    }

    @staticmethod
    def get_leave_day_units(
        *,
        start_date: date,
        end_date: date,
        half_day_start: bool = False,
        half_day_end: bool = False,
    ) -> Decimal:
        total_days = Decimal((end_date - start_date).days + 1)
        if half_day_start:
            total_days -= Decimal("0.5")
        if half_day_end:
            total_days -= Decimal("0.5")
        return total_days

    @staticmethod
    def _quantize_days(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.00"))

    def calculate_leave_days(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
        half_day_start: bool = False,
        half_day_end: bool = False,
        working_time_service: WorkingTimeService | None = None,
    ) -> Decimal:
        working_time_service = working_time_service or WorkingTimeService()
        total_days = Decimal("0.00")
        current_date = start_date

        while current_date <= end_date:
            if working_time_service.get_target_minutes_for_date(employee, current_date) > 0:
                day_units = Decimal("1.00")
                if current_date == start_date and half_day_start:
                    day_units -= Decimal("0.50")
                if current_date == end_date and half_day_end:
                    day_units -= Decimal("0.50")
                total_days += day_units
            current_date = current_date + timedelta(days=1)

        return self._quantize_days(total_days)

    def calculate_leave_days_for_request(
        self,
        leave_request: LeaveRequest,
        *,
        working_time_service: WorkingTimeService | None = None,
    ) -> Decimal:
        return self.calculate_leave_days(
            leave_request.employee,
            start_date=leave_request.start_date,
            end_date=leave_request.end_date,
            half_day_start=leave_request.half_day_start,
            half_day_end=leave_request.half_day_end,
            working_time_service=working_time_service,
        )

    def get_approved_leave_requests(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
        leave_type: str | None = None,
    ):
        queryset = (
            self.get_queryset()
            .filter(employee=employee, status=LeaveRequest.Status.APPROVED)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
        )
        if leave_type:
            queryset = queryset.filter(leave_type=leave_type)
        return queryset.order_by("start_date", "pk")

    def get_approved_vacation_days_for_year(
        self,
        employee: EmployeeProfile,
        year: int,
        *,
        working_time_service: WorkingTimeService | None = None,
    ) -> Decimal:
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        total_days = Decimal("0.00")

        for leave_request in self.get_approved_leave_requests(
            employee,
            start_date=year_start,
            end_date=year_end,
            leave_type=LeaveRequest.LeaveType.VACATION,
        ):
            total_days += self.calculate_leave_days(
                employee,
                start_date=max(leave_request.start_date, year_start),
                end_date=min(leave_request.end_date, year_end),
                half_day_start=leave_request.half_day_start and leave_request.start_date >= year_start,
                half_day_end=leave_request.half_day_end and leave_request.end_date <= year_end,
                working_time_service=working_time_service,
            )

        return self._quantize_days(total_days)

    def get_vacation_entitlement_total(
        self,
        employee: EmployeeProfile,
        year: int,
    ) -> Decimal:
        entitlement = VacationEntitlement.objects.filter(employee=employee, year=year).first()
        if entitlement is not None:
            return entitlement.total_days
        return self._quantize_days(Decimal(employee.vacation_days_per_year))

    def get_bridge_days_for_year(
        self,
        employee: EmployeeProfile,
        year: int,
        *,
        working_time_service: WorkingTimeService | None = None,
    ) -> Decimal:
        working_time_service = working_time_service or WorkingTimeService()
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        bridge_holidays = (
            CompanyHoliday.objects.filter(
                is_active=True,
                is_bridge_day=True,
                start_date__lte=year_end,
                end_date__gte=year_start,
            ).order_by("start_date")
        )
        total = Decimal("0.00")
        for bridge in bridge_holidays:
            current_date = max(bridge.start_date, year_start)
            last_date = min(bridge.end_date, year_end)
            while current_date <= last_date:
                if working_time_service.get_target_minutes_for_date(employee, current_date) > 0:
                    total += Decimal("1.00")
                current_date = current_date + timedelta(days=1)
        return self._quantize_days(total)

    def get_remaining_vacation_days_for_year(
        self,
        employee: EmployeeProfile,
        year: int,
        *,
        working_time_service: WorkingTimeService | None = None,
    ) -> Decimal:
        total_entitlement = self.get_vacation_entitlement_total(employee, year)
        approved_days = self.get_approved_vacation_days_for_year(
            employee,
            year,
            working_time_service=working_time_service,
        )
        bridge_days = self.get_bridge_days_for_year(
            employee,
            year,
            working_time_service=working_time_service,
        )
        return self._quantize_days(total_entitlement - approved_days - bridge_days)

    def get_approved_leave_minutes_for_month(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
        *,
        working_time_service: WorkingTimeService | None = None,
    ) -> int:
        working_time_service = working_time_service or WorkingTimeService()
        month_days = working_time_service.get_days_in_month(year, month)
        if not month_days:
            return 0
        start_date = month_days[0]
        end_date = month_days[-1]
        total_minutes = Decimal("0")

        for leave_request in self.get_approved_leave_requests(employee, start_date=start_date, end_date=end_date):
            current_date = max(leave_request.start_date, start_date)
            last_date = min(leave_request.end_date, end_date)
            while current_date <= last_date:
                target_minutes = Decimal(working_time_service.get_target_minutes_for_date(employee, current_date))
                if current_date == leave_request.start_date and leave_request.half_day_start:
                    target_minutes /= Decimal("2")
                if current_date == leave_request.end_date and leave_request.half_day_end:
                    target_minutes /= Decimal("2")
                total_minutes += target_minutes
                current_date = current_date + timedelta(days=1)

        return int(total_minutes)

    def has_overlapping_approved_leave(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
        exclude_leave_request_id: int | None = None,
    ) -> bool:
        queryset = (
            self.get_queryset()
            .filter(employee=employee, status=LeaveRequest.Status.APPROVED)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
        )
        if exclude_leave_request_id:
            queryset = queryset.exclude(pk=exclude_leave_request_id)
        return queryset.exists()

    @classmethod
    def validate_status_transition(cls, current_status: str, target_status: str) -> None:
        if current_status == target_status:
            return
        allowed_statuses = cls.STATUS_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_statuses:
            raise ValidationError(
                {"status": f"Statuswechsel von {current_status} nach {target_status} ist nicht erlaubt."}
            )

    def validate_leave_request_conflicts(self, leave_request: LeaveRequest) -> None:
        errors: dict[str, str] = {}
        if self.has_overlapping_approved_leave(
            leave_request.employee,
            start_date=leave_request.start_date,
            end_date=leave_request.end_date,
            exclude_leave_request_id=leave_request.pk,
        ):
            errors["start_date"] = "Der Antrag ueberschneidet sich mit bereits freigegebenem Urlaub."

        overlaps_sick_leave = SickLeave.objects.filter(
            employee=leave_request.employee,
            start_date__lte=leave_request.end_date,
            end_date__gte=leave_request.start_date,
        ).exists()
        if overlaps_sick_leave:
            errors["start_date"] = "Der Antrag ueberschneidet sich mit einer bestehenden Krankmeldung."
        if HolidayService().has_company_holiday_overlap(
            start_date=leave_request.start_date,
            end_date=leave_request.end_date,
        ):
            errors["start_date"] = "Der Antrag ueberschneidet sich mit einem Betriebsurlaub."

        if errors:
            raise ValidationError(errors)

    def approve_leave_request(self, leave_request: LeaveRequest, *, approved_by) -> LeaveRequest:
        self.validate_status_transition(leave_request.status, LeaveRequest.Status.APPROVED)
        self.validate_leave_request_conflicts(leave_request)
        leave_request.calculated_days = self.calculate_leave_days_for_request(leave_request)
        leave_request.status = LeaveRequest.Status.APPROVED
        leave_request.approved_by = approved_by
        leave_request.approved_at = timezone.now()
        leave_request.full_clean()
        leave_request.save()
        return leave_request

    def reject_leave_request(self, leave_request: LeaveRequest, *, approved_by) -> LeaveRequest:
        self.validate_status_transition(leave_request.status, LeaveRequest.Status.REJECTED)
        leave_request.calculated_days = self.calculate_leave_days_for_request(leave_request)
        leave_request.status = LeaveRequest.Status.REJECTED
        leave_request.approved_by = approved_by
        leave_request.approved_at = timezone.now()
        leave_request.full_clean()
        leave_request.save()
        return leave_request

    def cancel_leave_request(self, leave_request: LeaveRequest) -> LeaveRequest:
        self.validate_status_transition(leave_request.status, LeaveRequest.Status.CANCELLED)
        leave_request.calculated_days = self.calculate_leave_days_for_request(leave_request)
        leave_request.status = LeaveRequest.Status.CANCELLED
        leave_request.full_clean()
        leave_request.save()
        return leave_request
