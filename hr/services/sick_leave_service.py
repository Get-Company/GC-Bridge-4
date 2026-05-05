from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError

from core.services import BaseService
from hr.models import EmployeeProfile, LeaveRequest, SickLeave
from hr.services.holiday_service import HolidayService


class SickLeaveService(BaseService):
    model = SickLeave

    def get_overlapping_sick_leaves(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
        exclude_sick_leave_id: int | None = None,
    ):
        queryset = self.get_queryset().filter(
            employee=employee,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        if exclude_sick_leave_id:
            queryset = queryset.exclude(pk=exclude_sick_leave_id)
        return queryset.order_by("start_date", "pk")

    def has_overlapping_sick_leave(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
        exclude_sick_leave_id: int | None = None,
    ) -> bool:
        return self.get_overlapping_sick_leaves(
            employee,
            start_date=start_date,
            end_date=end_date,
            exclude_sick_leave_id=exclude_sick_leave_id,
        ).exists()

    def has_overlapping_approved_leave(
        self,
        employee: EmployeeProfile,
        *,
        start_date: date,
        end_date: date,
        exclude_leave_request_id: int | None = None,
    ) -> bool:
        queryset = LeaveRequest.objects.filter(
            employee=employee,
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        if exclude_leave_request_id:
            queryset = queryset.exclude(pk=exclude_leave_request_id)
        return queryset.exists()

    def validate_sick_leave(self, sick_leave: SickLeave) -> None:
        errors: dict[str, str] = {}
        if self.has_overlapping_sick_leave(
            sick_leave.employee,
            start_date=sick_leave.start_date,
            end_date=sick_leave.end_date,
            exclude_sick_leave_id=sick_leave.pk,
        ):
            errors["start_date"] = "Dieser Krankheitseintrag ueberschneidet sich mit einer bestehenden Krankmeldung."
        if self.has_overlapping_approved_leave(
            sick_leave.employee,
            start_date=sick_leave.start_date,
            end_date=sick_leave.end_date,
        ):
            errors["start_date"] = "Die Krankmeldung ueberschneidet sich mit bereits freigegebenem Urlaub."
        if HolidayService().has_company_holiday_overlap(
            start_date=sick_leave.start_date,
            end_date=sick_leave.end_date,
        ):
            errors["start_date"] = "Die Krankmeldung ueberschneidet sich mit einem Betriebsurlaub."
        if errors:
            raise ValidationError(errors)
