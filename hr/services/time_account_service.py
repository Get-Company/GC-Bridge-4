from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.services import BaseService
from hr.models import EmployeeProfile, TimeAccountEntry


class TimeAccountService(BaseService):
    model = TimeAccountEntry
    STATUS_TRANSITIONS = {
        TimeAccountEntry.Status.DRAFT: {TimeAccountEntry.Status.REQUESTED},
        TimeAccountEntry.Status.REQUESTED: {
            TimeAccountEntry.Status.APPROVED,
            TimeAccountEntry.Status.REJECTED,
        },
        TimeAccountEntry.Status.APPROVED: set(),
        TimeAccountEntry.Status.REJECTED: set(),
    }

    @staticmethod
    def split_minutes(entries) -> tuple[int, int]:
        overtime_minutes = 0
        minus_minutes = 0
        for entry in entries:
            minutes = int(getattr(entry, "minutes", 0) or 0)
            if minutes > 0:
                overtime_minutes += minutes
            elif minutes < 0:
                minus_minutes += minutes
        return overtime_minutes, minus_minutes

    def get_time_account_balance(
        self,
        employee: EmployeeProfile,
        *,
        until_date: date | None = None,
    ) -> int:
        queryset = self.get_queryset().filter(employee=employee, status=TimeAccountEntry.Status.APPROVED)
        if until_date is not None:
            queryset = queryset.filter(date__lte=until_date)
        return sum(queryset.values_list("minutes", flat=True))

    def get_month_time_entries(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
    ):
        return self.get_queryset().filter(employee=employee, date__year=year, date__month=month).order_by("date", "pk")

    def get_approved_minutes_for_month(
        self,
        employee: EmployeeProfile,
        year: int,
        month: int,
    ) -> dict[str, int]:
        entries = self.get_month_time_entries(employee, year, month).filter(status=TimeAccountEntry.Status.APPROVED)
        overtime_minutes, minus_minutes = self.split_minutes(entries)
        return {
            "overtime_minutes": overtime_minutes,
            "minus_minutes": minus_minutes,
            "balance_minutes": overtime_minutes + minus_minutes,
        }

    @classmethod
    def validate_status_transition(cls, current_status: str, target_status: str) -> None:
        if current_status == target_status:
            return
        allowed_statuses = cls.STATUS_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_statuses:
            raise ValidationError(
                {"status": f"Statuswechsel von {current_status} nach {target_status} ist nicht erlaubt."}
            )

    def approve_entry(self, entry: TimeAccountEntry, *, approved_by) -> TimeAccountEntry:
        self.validate_status_transition(entry.status, TimeAccountEntry.Status.APPROVED)
        entry.status = TimeAccountEntry.Status.APPROVED
        entry.approved_by = approved_by
        entry.approved_at = timezone.now()
        entry.full_clean()
        entry.save()
        return entry

    def reject_entry(self, entry: TimeAccountEntry, *, approved_by) -> TimeAccountEntry:
        self.validate_status_transition(entry.status, TimeAccountEntry.Status.REJECTED)
        entry.status = TimeAccountEntry.Status.REJECTED
        entry.approved_by = approved_by
        entry.approved_at = timezone.now()
        entry.full_clean()
        entry.save()
        return entry
