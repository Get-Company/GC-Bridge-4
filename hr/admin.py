from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from unfold.contrib.filters.admin import BooleanRadioFilter, RangeDateTimeFilter, RelatedDropdownFilter

from core.admin import BaseAdmin, BaseTabularInline
from hr.models import (
    CompanyHoliday,
    Department,
    EmployeeProfile,
    EmployeeWorkSchedule,
    HolidayCalendar,
    LeaveRequest,
    MonthlyWorkSummary,
    PublicHoliday,
    SchoolHoliday,
    SickLeave,
    TimeAccountEntry,
    WorkSchedule,
    WorkScheduleDay,
)
from hr.services import (
    AccessService,
    LeaveService,
    MonthlySummaryService,
    OpenHolidaysApiError,
    OpenHolidaysService,
    TimeAccountService,
)


class WorkScheduleDayInline(BaseTabularInline):
    model = WorkScheduleDay
    fields = (
        "weekday",
        "is_working_day",
        "start_time",
        "end_time",
        "break_minutes",
        "target_minutes",
        "created_at",
        "updated_at",
    )


class HrScopedAdminMixin:
    employee_lookup = "employee"
    manager_permission_name = "can_manage_master_data"

    @property
    def access_service(self) -> AccessService:
        return AccessService()

    def can_manage(self, request) -> bool:
        return getattr(self.access_service, self.manager_permission_name)(request.user)

    def get_visible_employee_queryset(self, request):
        return self.access_service.get_visible_employee_queryset(request.user)

    def get_visible_department_queryset(self, request):
        return self.access_service.get_visible_department_queryset(request.user)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.model is EmployeeProfile:
            return self.get_visible_employee_queryset(request)
        if self.model is Department:
            return self.get_visible_department_queryset(request)
        if self.employee_lookup:
            return self.access_service.filter_queryset_for_user(
                request.user,
                queryset,
                employee_field=self.employee_lookup,
            )
        return queryset if self.can_manage(request) else queryset.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "employee":
            kwargs["queryset"] = self.get_visible_employee_queryset(request)
        elif db_field.name == "department":
            kwargs["queryset"] = self.get_visible_department_queryset(request)
        elif db_field.name == "holiday_calendar":
            kwargs["queryset"] = HolidayCalendar.objects.filter(is_active=True).order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not self.can_manage(request):
            return {}
        return actions


@admin.register(Department)
class DepartmentAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")
    list_filter = [
        ("is_active", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(HolidayCalendar)
class HolidayCalendarAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    list_display = ("name", "region_code", "is_default", "is_active", "created_at")
    search_fields = ("name", "region_code")
    list_filter = [
        ("is_default", BooleanRadioFilter),
        ("is_active", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    list_display = (
        "user",
        "full_name_display",
        "employee_number",
        "department",
        "holiday_calendar",
        "short_code",
        "color",
        "is_active_employee",
    )
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "employee_number",
        "short_code",
        "phone",
    )
    list_filter = [
        ("department", RelatedDropdownFilter),
        ("is_active_employee", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]

    def has_module_permission(self, request):
        return self.access_service.can_view_calendar(request.user)

    def has_view_permission(self, request, obj=None):
        if self.can_manage(request):
            return True
        if obj is None:
            return self.access_service.can_view_calendar(request.user)
        return self.get_visible_employee_queryset(request).filter(pk=obj.pk).exists()

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)

    @admin.display(description="Name", ordering="user__last_name")
    def full_name_display(self, obj: EmployeeProfile) -> str:
        return obj.full_name


@admin.register(WorkSchedule)
class WorkScheduleAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    list_display = ("name", "is_active", "created_at")
    search_fields = ("name", "description")
    list_filter = [
        ("is_active", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    inlines = (WorkScheduleDayInline,)

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(PublicHoliday)
class PublicHolidayAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    change_list_template = "admin/hr/publicholiday/change_list.html"
    list_display = ("name", "date", "calendar", "is_half_day", "is_active", "created_at")
    search_fields = ("name", "calendar__name")
    list_filter = [
        ("calendar", RelatedDropdownFilter),
        ("is_half_day", BooleanRadioFilter),
        ("is_active", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    date_hierarchy = "date"

    @staticmethod
    def _get_openholidays_year(raw_value: str | None) -> int:
        current_year = date.today().year
        try:
            parsed_year = int((raw_value or "").strip())
        except (TypeError, ValueError):
            return current_year
        if parsed_year < 2000 or parsed_year > current_year + 5:
            return current_year
        return parsed_year

    @staticmethod
    def _get_openholidays_value(raw_value: str | None, *, default: str) -> str:
        cleaned = (raw_value or "").strip().upper()
        return cleaned or default

    def get_urls(self):
        custom_urls = [
            path(
                "openholidays/",
                self.admin_site.admin_view(self.openholidays_view),
                name="hr_publicholiday_openholidays",
            ),
        ]
        return custom_urls + super().get_urls()

    def openholidays_view(self, request):
        if not self.can_manage(request):
            raise PermissionDenied

        data = request.POST if request.method == "POST" else request.GET
        service = OpenHolidaysService()
        year = self._get_openholidays_year(data.get("year"))
        country_iso_code = self._get_openholidays_value(
            data.get("country_iso_code"),
            default=service.DEFAULT_COUNTRY_ISO_CODE,
        )
        language_iso_code = self._get_openholidays_value(
            data.get("language_iso_code"),
            default=service.DEFAULT_LANGUAGE_ISO_CODE,
        )
        subdivision_code = self._get_openholidays_value(
            data.get("subdivision_code"),
            default=service.DEFAULT_SUBDIVISION_CODE,
        )
        try:
            selected_calendar_id = int((data.get("calendar_id") or "").strip())
        except (TypeError, ValueError):
            selected_calendar_id = None

        holiday_calendars = HolidayCalendar.objects.order_by("name", "pk")
        selected_calendar = None
        if selected_calendar_id is not None:
            selected_calendar = holiday_calendars.filter(pk=selected_calendar_id).first()
        if selected_calendar is None:
            selected_calendar = holiday_calendars.filter(is_default=True).first() or holiday_calendars.first()
            selected_calendar_id = selected_calendar.pk if selected_calendar else None

        public_holidays: list[dict] = []
        school_holidays: list[dict] = []
        try:
            public_holidays = service.fetch_public_holidays(
                year=year,
                country_iso_code=country_iso_code,
                language_iso_code=language_iso_code,
                subdivision_code=subdivision_code,
            )
            school_holidays = service.fetch_school_holidays(
                year=year,
                country_iso_code=country_iso_code,
                language_iso_code=language_iso_code,
                subdivision_code=subdivision_code,
            )
        except OpenHolidaysApiError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)

        if request.method == "POST" and request.POST.get("action") == "import_public_holidays":
            if selected_calendar is None:
                self.message_user(request, "Bitte zuerst einen Feiertagskalender auswaehlen.", level=messages.ERROR)
            elif not public_holidays:
                self.message_user(
                    request,
                    "Es konnten keine Feiertage geladen werden. Import wurde nicht ausgefuehrt.",
                    level=messages.WARNING,
                )
            else:
                result = service.import_public_holidays(calendar=selected_calendar, holidays=public_holidays)
                self.message_user(
                    request,
                    (
                        f"Feiertage importiert fuer '{selected_calendar.name}': "
                        f"{result['created']} neu, {result['updated']} aktualisiert, "
                        f"{result['unchanged']} unveraendert."
                    ),
                )
                query_string = urlencode(
                    {
                        "year": year,
                        "country_iso_code": country_iso_code,
                        "language_iso_code": language_iso_code,
                        "subdivision_code": subdivision_code,
                        "calendar_id": selected_calendar.pk,
                    }
                )
                return HttpResponseRedirect(f"{reverse('admin:hr_publicholiday_openholidays')}?{query_string}")

        if request.method == "POST" and request.POST.get("action") == "import_school_holidays":
            if selected_calendar is None:
                self.message_user(request, "Bitte zuerst einen Feiertagskalender auswaehlen.", level=messages.ERROR)
            elif not school_holidays:
                self.message_user(
                    request,
                    "Es konnten keine Schulferien geladen werden. Import wurde nicht ausgefuehrt.",
                    level=messages.WARNING,
                )
            else:
                result = service.import_school_holidays(calendar=selected_calendar, holidays=school_holidays)
                self.message_user(
                    request,
                    (
                        f"Ferientermine importiert fuer '{selected_calendar.name}': "
                        f"{result['created']} neu, {result['updated']} aktualisiert, "
                        f"{result['unchanged']} unveraendert."
                    ),
                )
                query_string = urlencode(
                    {
                        "year": year,
                        "country_iso_code": country_iso_code,
                        "language_iso_code": language_iso_code,
                        "subdivision_code": subdivision_code,
                        "calendar_id": selected_calendar.pk,
                    }
                )
                return HttpResponseRedirect(f"{reverse('admin:hr_publicholiday_openholidays')}?{query_string}")

        if request.method == "POST" and request.POST.get("action") == "import_all_holidays":
            if selected_calendar is None:
                self.message_user(request, "Bitte zuerst einen Feiertagskalender auswaehlen.", level=messages.ERROR)
            else:
                public_result = service.import_public_holidays(calendar=selected_calendar, holidays=public_holidays)
                school_result = service.import_school_holidays(calendar=selected_calendar, holidays=school_holidays)
                self.message_user(
                    request,
                    (
                        f"Import fuer '{selected_calendar.name}' abgeschlossen. "
                        f"Feiertage: {public_result['created']} neu, {public_result['updated']} aktualisiert, "
                        f"{public_result['unchanged']} unveraendert. "
                        f"Ferientermine: {school_result['created']} neu, {school_result['updated']} aktualisiert, "
                        f"{school_result['unchanged']} unveraendert."
                    ),
                )
                query_string = urlencode(
                    {
                        "year": year,
                        "country_iso_code": country_iso_code,
                        "language_iso_code": language_iso_code,
                        "subdivision_code": subdivision_code,
                        "calendar_id": selected_calendar.pk,
                    }
                )
                return HttpResponseRedirect(f"{reverse('admin:hr_publicholiday_openholidays')}?{query_string}")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "OpenHolidays Import",
            "subtitle": "Feiertage und Schulferien fuer das aktuelle Jahr laden und importieren",
            "holiday_calendars": holiday_calendars,
            "selected_calendar_id": selected_calendar_id,
            "year": year,
            "country_iso_code": country_iso_code,
            "language_iso_code": language_iso_code,
            "subdivision_code": subdivision_code,
            "public_holidays": public_holidays,
            "school_holidays": school_holidays,
            "public_holiday_count": len(public_holidays),
            "school_holiday_count": len(school_holidays),
            "import_url": reverse("admin:hr_publicholiday_openholidays"),
            "changelist_url": reverse("admin:hr_publicholiday_changelist"),
        }
        return TemplateResponse(request, "admin/hr/openholidays_import.html", context)

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(SchoolHoliday)
class SchoolHolidayAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    list_display = ("name", "start_date", "end_date", "calendar", "is_active", "created_at")
    search_fields = ("name", "calendar__name", "source_subdivisions", "note")
    list_filter = [
        ("calendar", RelatedDropdownFilter),
        ("is_active", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    date_hierarchy = "start_date"

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(CompanyHoliday)
class CompanyHolidayAdmin(HrScopedAdminMixin, BaseAdmin):
    employee_lookup = None
    list_display = ("name", "start_date", "end_date", "counts_as_vacation", "is_active", "created_at")
    search_fields = ("name", "note")
    list_filter = [
        ("counts_as_vacation", BooleanRadioFilter),
        ("is_active", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    date_hierarchy = "start_date"

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(EmployeeWorkSchedule)
class EmployeeWorkScheduleAdmin(HrScopedAdminMixin, BaseAdmin):
    list_display = ("employee", "schedule", "valid_from", "valid_until", "created_at")
    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "schedule__name",
    )
    list_filter = [
        ("employee__department", RelatedDropdownFilter),
        ("schedule", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    date_hierarchy = "valid_from"

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(HrScopedAdminMixin, BaseAdmin):
    manager_permission_name = "can_manage_leave_requests"
    list_display = (
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "status",
        "approved_by",
        "approved_at",
    )
    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "employee__short_code",
        "reason",
    )
    list_filter = [
        ("status", admin.ChoicesFieldListFilter),
        ("leave_type", admin.ChoicesFieldListFilter),
        ("employee__department", RelatedDropdownFilter),
        ("employee", RelatedDropdownFilter),
    ]
    actions = ("approve_selected", "reject_selected", "cancel_selected")
    date_hierarchy = "start_date"

    @admin.action(description="Ausgewaehlte Urlaubsantraege freigeben")
    def approve_selected(self, request, queryset):
        service = LeaveService()
        updated = 0
        errors = 0
        for leave_request in queryset.select_related("employee"):
            try:
                service.approve_leave_request(leave_request, approved_by=request.user)
                updated += 1
            except ValidationError:
                errors += 1
        if updated:
            self.message_user(request, f"{updated} Urlaubsantraege wurden freigegeben.")
        if errors:
            self.message_user(
                request,
                f"{errors} Urlaubsantraege konnten wegen Status- oder Konfliktpruefung nicht freigegeben werden.",
                level=messages.WARNING,
            )

    @admin.action(description="Ausgewaehlte Urlaubsantraege ablehnen")
    def reject_selected(self, request, queryset):
        service = LeaveService()
        updated = 0
        errors = 0
        for leave_request in queryset.select_related("employee"):
            try:
                service.reject_leave_request(leave_request, approved_by=request.user)
                updated += 1
            except ValidationError:
                errors += 1
        if updated:
            self.message_user(request, f"{updated} Urlaubsantraege wurden abgelehnt.", level=messages.WARNING)
        if errors:
            self.message_user(
                request,
                f"{errors} Urlaubsantraege konnten nicht abgelehnt werden.",
                level=messages.WARNING,
            )

    @admin.action(description="Ausgewaehlte Urlaubsantraege stornieren")
    def cancel_selected(self, request, queryset):
        service = LeaveService()
        updated = 0
        errors = 0
        for leave_request in queryset.select_related("employee"):
            try:
                service.cancel_leave_request(leave_request)
                updated += 1
            except ValidationError:
                errors += 1
        if updated:
            self.message_user(request, f"{updated} Urlaubsantraege wurden storniert.", level=messages.WARNING)
        if errors:
            self.message_user(
                request,
                f"{errors} Urlaubsantraege konnten nicht storniert werden.",
                level=messages.WARNING,
            )

    def has_module_permission(self, request):
        return self.access_service.can_view_calendar(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return self.access_service.can_view_calendar(request.user)
        return self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_add_permission(self, request):
        return self.can_manage(request) or self.access_service.get_user_employee_profile(request.user) is not None

    def has_change_permission(self, request, obj=None):
        if self.can_manage(request):
            return True
        if obj is None:
            return False
        employee_profile = self.access_service.get_user_employee_profile(request.user)
        if employee_profile is None:
            return False
        return obj.employee_id == employee_profile.pk and obj.status == LeaveRequest.Status.REQUESTED

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj=obj)

    def get_exclude(self, request, obj=None):
        if self.can_manage(request):
            return ("approved_by", "approved_at")
        return ("status", "approved_by", "approved_at")

    def save_model(self, request, obj, form, change):
        if not self.can_manage(request):
            employee_profile = self.access_service.get_user_employee_profile(request.user)
            if employee_profile is None:
                raise ValidationError("Ohne Mitarbeiterprofil kann kein Urlaubsantrag gespeichert werden.")
            obj.employee = employee_profile
        super().save_model(request, obj, form, change)


@admin.register(SickLeave)
class SickLeaveAdmin(HrScopedAdminMixin, BaseAdmin):
    manager_permission_name = "can_manage_sick_leaves"
    list_display = ("employee", "start_date", "end_date", "has_certificate", "created_at")
    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "employee__short_code",
        "note",
    )
    list_filter = [
        ("employee__department", RelatedDropdownFilter),
        ("employee", RelatedDropdownFilter),
        ("has_certificate", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    date_hierarchy = "start_date"

    def has_module_permission(self, request):
        return self.can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(TimeAccountEntry)
class TimeAccountEntryAdmin(HrScopedAdminMixin, BaseAdmin):
    manager_permission_name = "can_manage_time_account"
    list_display = ("employee", "date", "entry_type", "minutes", "status", "approved_by", "approved_at")
    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "employee__short_code",
        "reason",
    )
    list_filter = [
        ("status", admin.ChoicesFieldListFilter),
        ("entry_type", admin.ChoicesFieldListFilter),
        ("employee__department", RelatedDropdownFilter),
        ("employee", RelatedDropdownFilter),
    ]
    actions = ("approve_selected", "reject_selected")
    date_hierarchy = "date"

    @admin.action(description="Ausgewaehlte Zeitbuchungen freigeben")
    def approve_selected(self, request, queryset):
        service = TimeAccountService()
        updated = 0
        errors = 0
        for entry in queryset.select_related("employee"):
            try:
                service.approve_entry(entry, approved_by=request.user)
                updated += 1
            except ValidationError:
                errors += 1
        if updated:
            self.message_user(request, f"{updated} Zeitbuchungen wurden freigegeben.")
        if errors:
            self.message_user(
                request,
                f"{errors} Zeitbuchungen konnten wegen Statuspruefung nicht freigegeben werden.",
                level=messages.WARNING,
            )

    @admin.action(description="Ausgewaehlte Zeitbuchungen ablehnen")
    def reject_selected(self, request, queryset):
        service = TimeAccountService()
        updated = 0
        errors = 0
        for entry in queryset.select_related("employee"):
            try:
                service.reject_entry(entry, approved_by=request.user)
                updated += 1
            except ValidationError:
                errors += 1
        if updated:
            self.message_user(request, f"{updated} Zeitbuchungen wurden abgelehnt.", level=messages.WARNING)
        if errors:
            self.message_user(
                request,
                f"{errors} Zeitbuchungen konnten nicht abgelehnt werden.",
                level=messages.WARNING,
            )

    def has_module_permission(self, request):
        return self.access_service.can_view_calendar(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return self.access_service.can_view_calendar(request.user)
        return self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_add_permission(self, request):
        return self.can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self.can_manage(request)


@admin.register(MonthlyWorkSummary)
class MonthlyWorkSummaryAdmin(HrScopedAdminMixin, BaseAdmin):
    manager_permission_name = "can_manage_monthly_summaries"
    list_display = (
        "employee",
        "year",
        "month",
        "target_minutes",
        "vacation_minutes",
        "sick_minutes",
        "overtime_minutes",
        "minus_minutes",
        "balance_minutes",
        "locked",
    )
    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "employee__short_code",
    )
    list_filter = [
        ("employee__department", RelatedDropdownFilter),
        ("employee", RelatedDropdownFilter),
        ("locked", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    actions = ("recalculate_selected", "lock_selected")

    @admin.action(description="Ausgewaehlte Monatsuebersichten neu berechnen")
    def recalculate_selected(self, request, queryset):
        recalculated = 0
        for summary in queryset.select_related("employee"):
            if summary.locked:
                continue
            MonthlySummaryService().recalculate_monthly_summary(summary.employee, summary.year, summary.month)
            recalculated += 1
        self.message_user(request, f"{recalculated} Monatsuebersichten wurden neu berechnet.")

    @admin.action(description="Ausgewaehlte Monatsuebersichten abschliessen")
    def lock_selected(self, request, queryset):
        locked = 0
        for summary in queryset:
            if summary.locked:
                continue
            MonthlySummaryService().lock_monthly_summary(summary)
            locked += 1
        self.message_user(request, f"{locked} Monatsuebersichten wurden abgeschlossen.")

    def has_module_permission(self, request):
        return self.access_service.can_view_calendar(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return self.access_service.can_view_calendar(request.user)
        return self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self.can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return False
