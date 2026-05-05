from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.template.response import TemplateResponse

from hr.services import AccessService, CalendarService


def _parse_iso_date(value: str | None, *, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _parse_employee_ids(request) -> list[int]:
    values = request.GET.getlist("employee")
    if not values:
        single_value = request.GET.get("employee", "").strip()
        if single_value:
            values = [item.strip() for item in single_value.split(",") if item.strip()]

    employee_ids: list[int] = []
    for value in values:
        try:
            employee_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return employee_ids


def hr_calendar_view(request):
    access_service = AccessService()
    if not access_service.can_view_calendar(request.user):
        raise PermissionDenied

    employee_queryset = access_service.get_visible_employee_queryset(request.user).order_by(
        "user__last_name",
        "user__first_name",
        "user__username",
    )
    department_queryset = access_service.get_visible_department_queryset(request.user).order_by("name")
    today = date.today()

    context = {
        **admin.site.each_context(request),
        "title": "Mitarbeiterkalender",
        "employees": employee_queryset,
        "departments": department_queryset,
        "default_month": today.strftime("%Y-%m"),
        "can_view_sick_leave_details": access_service.can_view_sick_leave_details(request.user),
    }
    return TemplateResponse(request, "admin/hr_calendar.html", context)


def hr_calendar_api(request):
    access_service = AccessService()
    if not access_service.can_view_calendar(request.user):
        raise PermissionDenied

    today = date.today()
    default_start = today.replace(day=1)
    default_end = today.replace(day=monthrange(today.year, today.month)[1])
    start_date = _parse_iso_date(request.GET.get("start"), fallback=default_start)
    end_date = _parse_iso_date(request.GET.get("end"), fallback=default_end)

    employee_queryset = access_service.get_visible_employee_queryset(request.user)
    department_id = request.GET.get("department", "").strip()
    if department_id:
        try:
            employee_queryset = employee_queryset.filter(department_id=int(department_id))
        except ValueError:
            pass

    employee_ids = _parse_employee_ids(request)
    if employee_ids:
        employee_queryset = employee_queryset.filter(pk__in=employee_ids)

    employee_queryset = employee_queryset.order_by("user__last_name", "user__first_name", "user__username")
    events = CalendarService().get_calendar_events_for_user(
        request.user,
        start_date=start_date,
        end_date=end_date,
        employees=employee_queryset,
    )

    return JsonResponse(
        {
            "events": events,
            "range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "filters": {
                "department": department_id,
                "employees": employee_ids,
            },
        }
    )
