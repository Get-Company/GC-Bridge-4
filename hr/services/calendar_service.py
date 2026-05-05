from __future__ import annotations

from datetime import date, timedelta

from core.services import BaseService
from hr.models import CompanyHoliday, EmployeeProfile, LeaveRequest, PublicHoliday, SickLeave, TimeAccountEntry
from hr.services.access_service import AccessService
from hr.services.holiday_service import HolidayService


class CalendarService(BaseService):
    model = EmployeeProfile

    @staticmethod
    def _normalize_employees(employees=None):
        if employees is None:
            return EmployeeProfile.objects.select_related("user", "department").all()
        if hasattr(employees, "select_related"):
            return employees.select_related("user", "department")
        employee_ids = [employee.pk for employee in employees]
        return EmployeeProfile.objects.select_related("user", "department").filter(pk__in=employee_ids)

    @staticmethod
    def _build_event(
        *,
        employee: EmployeeProfile | None,
        title_suffix: str,
        start_date: date,
        end_date: date,
        event_type: str,
        color: str | None = None,
    ) -> dict[str, str]:
        title_prefix = employee.short_code if employee is not None else ""
        return {
            "title": f"{title_prefix} {title_suffix}".strip(),
            "start": start_date.isoformat(),
            "end": (end_date + timedelta(days=1)).isoformat(),
            "color": color or (employee.color if employee is not None else "#64748b"),
            "employee": employee.full_name if employee is not None else "",
            "employee_id": employee.pk if employee is not None else None,
            "department": employee.department.name if employee is not None and employee.department_id else "",
            "short_code": employee.short_code if employee is not None else "",
            "type": event_type,
            "allDay": True,
        }

    def get_leave_events(self, start_date: date, end_date: date, employees=None) -> list[dict[str, str]]:
        employee_queryset = self._normalize_employees(employees)
        employee_map = {employee.pk: employee for employee in employee_queryset}
        leave_requests = (
            LeaveRequest.objects.filter(employee__in=employee_queryset, status=LeaveRequest.Status.APPROVED)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
            .select_related("employee__user")
            .order_by("start_date", "pk")
        )
        return [
            self._build_event(
                employee=employee_map[leave_request.employee_id],
                title_suffix=leave_request.get_leave_type_display(),
                start_date=max(leave_request.start_date, start_date),
                end_date=min(leave_request.end_date, end_date),
                event_type=leave_request.leave_type,
            )
            for leave_request in leave_requests
        ]

    def get_sick_leave_events(
        self,
        start_date: date,
        end_date: date,
        employees=None,
        *,
        include_sensitive_labels: bool = False,
    ) -> list[dict[str, str]]:
        employee_queryset = self._normalize_employees(employees)
        employee_map = {employee.pk: employee for employee in employee_queryset}
        sick_leaves = (
            SickLeave.objects.filter(employee__in=employee_queryset)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
            .select_related("employee__user")
            .order_by("start_date", "pk")
        )
        return [
            self._build_event(
                employee=employee_map[sick_leave.employee_id],
                title_suffix="Krank" if include_sensitive_labels else "Abwesend",
                start_date=max(sick_leave.start_date, start_date),
                end_date=min(sick_leave.end_date, end_date),
                event_type="sick_leave",
            )
            for sick_leave in sick_leaves
        ]

    def get_time_account_events(self, start_date: date, end_date: date, employees=None) -> list[dict[str, str]]:
        employee_queryset = self._normalize_employees(employees)
        employee_map = {employee.pk: employee for employee in employee_queryset}
        entries = (
            TimeAccountEntry.objects.filter(employee__in=employee_queryset, status=TimeAccountEntry.Status.APPROVED)
            .filter(date__gte=start_date, date__lte=end_date)
            .select_related("employee__user")
            .order_by("date", "pk")
        )
        return [
            self._build_event(
                employee=employee_map[entry.employee_id],
                title_suffix=f"{entry.minutes:+} Min",
                start_date=entry.date,
                end_date=entry.date,
                event_type=entry.entry_type,
            )
            for entry in entries
        ]

    def get_public_holiday_events(self, start_date: date, end_date: date, employees=None) -> list[dict[str, str]]:
        employee_queryset = self._normalize_employees(employees)
        holiday_service = HolidayService()
        calendar_ids = [
            calendar_id
            for calendar_id in employee_queryset.values_list("holiday_calendar_id", flat=True).distinct()
            if calendar_id
        ]
        if employee_queryset.filter(holiday_calendar__isnull=True).exists():
            default_calendar = holiday_service.get_default_holiday_calendar()
            if default_calendar is not None:
                calendar_ids.append(default_calendar.pk)
        public_holidays = (
            PublicHoliday.objects.filter(calendar_id__in=calendar_ids, is_active=True)
            .filter(date__gte=start_date, date__lte=end_date)
            .select_related("calendar")
            .order_by("date", "calendar__name", "pk")
        )
        seen_keys = set()
        events = []
        for public_holiday in public_holidays:
            key = (public_holiday.calendar_id, public_holiday.date, public_holiday.name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events.append(
                self._build_event(
                    employee=None,
                    title_suffix=f"Feiertag: {public_holiday.name}",
                    start_date=public_holiday.date,
                    end_date=public_holiday.date,
                    event_type="public_holiday",
                    color="#475569",
                )
            )
        return events

    def get_company_holiday_events(self, start_date: date, end_date: date) -> list[dict[str, str]]:
        company_holidays = (
            CompanyHoliday.objects.filter(is_active=True)
            .filter(start_date__lte=end_date, end_date__gte=start_date)
            .order_by("start_date", "pk")
        )
        return [
            self._build_event(
                employee=None,
                title_suffix=f"Betriebsurlaub: {company_holiday.name}",
                start_date=max(company_holiday.start_date, start_date),
                end_date=min(company_holiday.end_date, end_date),
                event_type="company_holiday",
                color="#7c3aed" if company_holiday.counts_as_vacation else "#9a3412",
            )
            for company_holiday in company_holidays
        ]

    def get_calendar_events(self, start_date: date, end_date: date, employees=None) -> list[dict[str, str]]:
        events = []
        events.extend(self.get_public_holiday_events(start_date, end_date, employees=employees))
        events.extend(self.get_company_holiday_events(start_date, end_date))
        events.extend(self.get_leave_events(start_date, end_date, employees=employees))
        events.extend(self.get_sick_leave_events(start_date, end_date, employees=employees))
        events.extend(self.get_time_account_events(start_date, end_date, employees=employees))
        return sorted(events, key=lambda event: (event["start"], event["title"]))

    def get_calendar_events_for_user(
        self,
        user,
        *,
        start_date: date,
        end_date: date,
        employees=None,
    ) -> list[dict[str, str]]:
        access_service = AccessService()
        employee_queryset = employees or access_service.get_visible_employee_queryset(user)
        events = []
        events.extend(self.get_public_holiday_events(start_date, end_date, employees=employee_queryset))
        events.extend(self.get_company_holiday_events(start_date, end_date))
        events.extend(self.get_leave_events(start_date, end_date, employees=employee_queryset))
        events.extend(
            self.get_sick_leave_events(
                start_date,
                end_date,
                employees=employee_queryset,
                include_sensitive_labels=access_service.can_view_sick_leave_details(user),
            )
        )
        events.extend(self.get_time_account_events(start_date, end_date, employees=employee_queryset))
        return sorted(events, key=lambda event: (event["start"], event["title"]))
