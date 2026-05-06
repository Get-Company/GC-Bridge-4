from __future__ import annotations

from datetime import date
from decimal import Decimal
import logging

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from unfold.decorators import action
from unfold.enums import ActionVariant
from unfold.contrib.filters.admin import BooleanRadioFilter, RangeDateTimeFilter, RelatedDropdownFilter

from core.admin import BaseAdmin, BaseTabularInline
from hr.forms import EmployeeProfileAdminForm, EmployeeWorkingTimeOverviewForm, OpenHolidaysImportForm, WorkScheduleDayInlineForm
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
    VacationEntitlement,
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
    WorkingTimeOverviewService,
)

logger = logging.getLogger(__name__)


class WorkScheduleDayInline(BaseTabularInline):
    model = WorkScheduleDay
    form = WorkScheduleDayInlineForm
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


class EmployeeWorkScheduleInline(BaseTabularInline):
    model = EmployeeWorkSchedule
    fk_name = "employee"
    fields = ("schedule", "valid_from", "valid_until", "created_at", "updated_at")
    autocomplete_fields = ("schedule",)


class VacationEntitlementInline(BaseTabularInline):
    model = VacationEntitlement
    fk_name = "employee"
    fields = ("year", "base_days", "carryover_days", "carryover_expires_on", "note", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    extra = 0
    ordering = ("-year",)


class LeaveRequestYearInline(BaseTabularInline):
    model = LeaveRequest
    fk_name = "employee"
    fields = ("leave_type", "start_date", "end_date", "half_day_start", "half_day_end", "status", "approved_at")
    readonly_fields = ("leave_type", "start_date", "end_date", "half_day_start", "half_day_end", "status", "approved_at")
    extra = 0
    can_delete = False
    ordering = ("-start_date",)

    def get_queryset(self, request):
        current_year = date.today().year
        return (
            super().get_queryset(request)
            .filter(start_date__year=current_year)
            .exclude(status=LeaveRequest.Status.CANCELLED)
            .order_by("-start_date")
        )

    def has_add_permission(self, request, obj=None):
        return False


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
    form = EmployeeProfileAdminForm
    actions_detail = ("working_time_overview_action",)
    readonly_fields = BaseAdmin.readonly_fields + ("vacation_entitlement_display", "approved_vacation_days_display", "bridge_days_display", "remaining_vacation_days_display")
    list_display = (
        "user",
        "full_name_display",
        "employee_number",
        "department",
        "holiday_calendar",
        "remaining_vacation_days_display",
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
    inlines = (VacationEntitlementInline, LeaveRequestYearInline, EmployeeWorkScheduleInline,)

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

    @staticmethod
    def _format_minutes(value: int) -> str:
        absolute_value = abs(int(value or 0))
        hours, minutes = divmod(absolute_value, 60)
        prefix = "-" if value < 0 else ""
        return f"{prefix}{hours:02d}:{minutes:02d} h"

    @classmethod
    def _format_units(cls, value: Decimal) -> str:
        return f"{Decimal(value or 0).quantize(Decimal('0.00')):.2f} Tage"

    def _decorate_overview_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        decorated_rows: list[dict[str, object]] = []
        for row in rows:
            row_copy = dict(row)
            row_copy["scheduled_minutes_display"] = self._format_minutes(int(row["scheduled_minutes"]))
            row_copy["planned_minutes_display"] = self._format_minutes(int(row["planned_minutes"]))
            row_copy["vacation_minutes_display"] = self._format_minutes(int(row["vacation_minutes"]))
            row_copy["special_leave_minutes_display"] = self._format_minutes(int(row["special_leave_minutes"]))
            row_copy["overtime_reduction_minutes_display"] = self._format_minutes(int(row["overtime_reduction_minutes"]))
            row_copy["sick_minutes_display"] = self._format_minutes(int(row["sick_minutes"]))
            row_copy["public_holiday_minutes_display"] = self._format_minutes(int(row["public_holiday_minutes"]))
            row_copy["company_holiday_minutes_display"] = self._format_minutes(int(row["company_holiday_minutes"]))
            row_copy["bridge_day_minutes_display"] = self._format_minutes(int(row["bridge_day_minutes"]))
            row_copy["overtime_minutes_display"] = self._format_minutes(int(row["overtime_minutes"]))
            row_copy["minus_minutes_display"] = self._format_minutes(int(row["minus_minutes"]))
            row_copy["scheduled_units_display"] = self._format_units(Decimal(row["scheduled_units"]))
            row_copy["planned_units_display"] = self._format_units(Decimal(row["planned_units"]))
            row_copy["vacation_units_display"] = self._format_units(Decimal(row["vacation_units"]))
            row_copy["special_leave_units_display"] = self._format_units(Decimal(row["special_leave_units"]))
            row_copy["overtime_reduction_units_display"] = self._format_units(Decimal(row["overtime_reduction_units"]))
            row_copy["sick_units_display"] = self._format_units(Decimal(row["sick_units"]))
            row_copy["public_holiday_units_display"] = self._format_units(Decimal(row["public_holiday_units"]))
            row_copy["company_holiday_units_display"] = self._format_units(Decimal(row["company_holiday_units"]))
            row_copy["bridge_day_units_display"] = self._format_units(Decimal(row["bridge_day_units"]))
            decorated_rows.append(row_copy)
        return decorated_rows

    @action(
        description=_("Arbeitszeit-Auswertung"),
        url_path="working-time-overview",
        icon="query_stats",
        variant=ActionVariant.PRIMARY,
        permissions=["working_time_overview_action"],
    )
    def working_time_overview_action(self, request, object_id):
        employee = self.get_object(request, object_id)
        if employee is None:
            raise PermissionDenied

        initial = EmployeeWorkingTimeOverviewForm.build_initial()
        form = EmployeeWorkingTimeOverviewForm(request.GET or None, initial=initial)
        if form.is_valid():
            start_date = form.cleaned_data["start_date"]
            end_date = form.cleaned_data["end_date"]
        else:
            start_date = initial["start_date"]
            end_date = initial["end_date"]

        overview = WorkingTimeOverviewService().build_range_overview(
            employee,
            start_date=start_date,
            end_date=end_date,
        )
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": employee,
            "title": f"Arbeitszeit-Auswertung: {employee.full_name}",
            "employee": employee,
            "form": form,
            "summary_row": self._decorate_overview_rows([overview["summary"]])[0],
            "weekly_rows": self._decorate_overview_rows(overview["weekly_rows"]),
            "monthly_rows": self._decorate_overview_rows(overview["monthly_rows"]),
            "yearly_rows": self._decorate_overview_rows(overview["yearly_rows"]),
            "daily_rows": self._decorate_overview_rows(overview["daily_rows"]),
            "time_account_balance_display": self._format_minutes(int(overview["time_account_balance_minutes"])),
            "change_url": reverse("admin:hr_employeeprofile_change", args=[employee.pk]),
        }
        return TemplateResponse(request, "admin/hr/employee_working_time_overview.html", context)

    def has_working_time_overview_action_permission(self, request, object_id=None):
        if object_id is None:
            return False
        return self.get_visible_employee_queryset(request).filter(pk=object_id).exists()

    @admin.display(description="Name", ordering="user__last_name")
    def full_name_display(self, obj: EmployeeProfile) -> str:
        return obj.full_name

    @admin.display(description="Urlaubskonto")
    def vacation_entitlement_display(self, obj: EmployeeProfile) -> str:
        from hr.models import VacationEntitlement
        current_year = date.today().year
        entitlement = VacationEntitlement.objects.filter(employee=obj, year=current_year).first()
        if entitlement is None:
            return f"{obj.vacation_days_per_year:.2f} Tage (aus Profil, kein Konto fuer {current_year})"
        parts = [f"Basis: {entitlement.base_days:.2f} Tage"]
        if entitlement.carryover_days > 0:
            if entitlement.effective_carryover_days > 0:
                parts.append(f"Uebertrag: +{entitlement.carryover_days:.2f} (verfaellt {entitlement.carryover_expires_on})")
            else:
                parts.append(f"Uebertrag: {entitlement.carryover_days:.2f} (verfallen seit {entitlement.carryover_expires_on})")
        parts.append(f"Gesamt: {entitlement.total_days:.2f} Tage")
        return " | ".join(parts)

    @admin.display(description="Genehmigter Urlaub")
    def approved_vacation_days_display(self, obj: EmployeeProfile) -> str:
        current_year = date.today().year
        approved_days = LeaveService().get_approved_vacation_days_for_year(obj, current_year)
        return f"{approved_days:.2f} Tage ({current_year})"

    @admin.display(description="Brueckentage")
    def bridge_days_display(self, obj: EmployeeProfile) -> str:
        current_year = date.today().year
        bridge_days = LeaveService().get_bridge_days_for_year(obj, current_year)
        if bridge_days == 0:
            return f"0.00 Tage ({current_year})"
        return f"{bridge_days:.2f} Tage ({current_year})"

    @admin.display(description="Resturlaub")
    def remaining_vacation_days_display(self, obj: EmployeeProfile) -> str:
        current_year = date.today().year
        remaining_days = LeaveService().get_remaining_vacation_days_for_year(obj, current_year)
        return f"{remaining_days:.2f} Tage ({current_year})"


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
    actions_list = ("openholidays_import_action",)
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

    @action(
        description=_("OpenHolidays Import"),
        url_path="openholidays-import",
        icon="cloud_download",
        variant=ActionVariant.PRIMARY,
        permissions=["openholidays_import_action"],
    )
    def openholidays_import_action(self, request):
        return HttpResponseRedirect(reverse("admin:hr_publicholiday_openholidays"))

    def has_openholidays_import_action_permission(self, request):
        return self.can_manage(request)

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

        service = OpenHolidaysService()
        import_action = (request.POST.get("import_action") or request.POST.get("action") or "").strip()
        holiday_calendars = HolidayCalendar.objects.order_by("name", "pk")
        initial = OpenHolidaysImportForm.build_initial()
        form = OpenHolidaysImportForm(
            request.POST or None,
            initial=initial,
            calendar_queryset=holiday_calendars,
        )
        debug_info: list[str] = [
            f"request_method={request.method}",
            f"import_action={import_action or '-'}",
            f"post_keys={', '.join(sorted(request.POST.keys())) if request.method == 'POST' else '-'}",
        ]

        form_is_valid = form.is_valid() if request.method == "POST" else False
        debug_info.append(f"form_is_valid={form_is_valid}")

        if request.method == "POST" and not form_is_valid:
            self.message_user(request, _("Bitte die Importparameter pruefen."), level=messages.ERROR)
            for field_name, errors in form.errors.items():
                debug_info.append(f"form_error[{field_name}]={'; '.join(errors)}")

        if request.method == "POST" and form_is_valid:
            year = int(form.cleaned_data["year"])
            country_iso_code = self._get_openholidays_value(
                form.cleaned_data["country_iso_code"],
                default=service.DEFAULT_COUNTRY_ISO_CODE,
            )
            language_iso_code = self._get_openholidays_value(
                form.cleaned_data["language_iso_code"],
                default=service.DEFAULT_LANGUAGE_ISO_CODE,
            )
            subdivision_code = self._get_openholidays_value(
                form.cleaned_data["subdivision_code"],
                default=service.DEFAULT_SUBDIVISION_CODE,
            )
            selected_calendar = form.cleaned_data["calendar"]
            debug_info.append(f"selected_calendar={selected_calendar.pk}:{selected_calendar.name}")
        else:
            year = self._get_openholidays_year(str(initial["year"]))
            country_iso_code = self._get_openholidays_value(
                str(initial["country_iso_code"]),
                default=service.DEFAULT_COUNTRY_ISO_CODE,
            )
            language_iso_code = self._get_openholidays_value(
                str(initial["language_iso_code"]),
                default=service.DEFAULT_LANGUAGE_ISO_CODE,
            )
            subdivision_code = self._get_openholidays_value(
                str(initial["subdivision_code"]),
                default=service.DEFAULT_SUBDIVISION_CODE,
            )
            selected_calendar = holiday_calendars.filter(pk=initial["calendar"]).first() if initial["calendar"] else None
            debug_info.append(
                "selected_calendar="
                + (f"{selected_calendar.pk}:{selected_calendar.name}" if selected_calendar is not None else "-")
            )

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
            debug_info.append(f"fetched_public_holidays={len(public_holidays)}")
            debug_info.append(f"fetched_school_holidays={len(school_holidays)}")
        except OpenHolidaysApiError as exc:
            debug_info.append(f"fetch_error={exc}")
            self.message_user(request, str(exc), level=messages.ERROR)

        if request.method == "POST" and import_action == "import_public_holidays":
            if selected_calendar is None:
                debug_info.append("import_public_holidays=aborted:no_calendar")
                self.message_user(request, "Bitte zuerst einen Feiertagskalender auswaehlen.", level=messages.ERROR)
            elif not public_holidays:
                debug_info.append("import_public_holidays=aborted:no_public_holidays")
                self.message_user(
                    request,
                    "Es konnten keine Feiertage geladen werden. Import wurde nicht ausgefuehrt.",
                    level=messages.WARNING,
                )
            else:
                result = service.import_public_holidays(calendar=selected_calendar, holidays=public_holidays)
                debug_info.append(
                    "import_public_holidays="
                    f"created:{result['created']} updated:{result['updated']} unchanged:{result['unchanged']}"
                )
                logger.info("OpenHolidays public import result: %s", debug_info[-1])
                self.message_user(
                    request,
                    (
                        f"Feiertage importiert fuer '{selected_calendar.name}': "
                        f"{result['created']} neu, {result['updated']} aktualisiert, "
                        f"{result['unchanged']} unveraendert."
                    ),
                )
                return HttpResponseRedirect(reverse("admin:hr_publicholiday_changelist"))

        if request.method == "POST" and import_action == "import_school_holidays":
            if selected_calendar is None:
                debug_info.append("import_school_holidays=aborted:no_calendar")
                self.message_user(request, "Bitte zuerst einen Feiertagskalender auswaehlen.", level=messages.ERROR)
            elif not school_holidays:
                debug_info.append("import_school_holidays=aborted:no_school_holidays")
                self.message_user(
                    request,
                    "Es konnten keine Schulferien geladen werden. Import wurde nicht ausgefuehrt.",
                    level=messages.WARNING,
                )
            else:
                result = service.import_school_holidays(calendar=selected_calendar, holidays=school_holidays)
                debug_info.append(
                    "import_school_holidays="
                    f"created:{result['created']} updated:{result['updated']} unchanged:{result['unchanged']}"
                )
                logger.info("OpenHolidays school import result: %s", debug_info[-1])
                self.message_user(
                    request,
                    (
                        f"Ferientermine importiert fuer '{selected_calendar.name}': "
                        f"{result['created']} neu, {result['updated']} aktualisiert, "
                        f"{result['unchanged']} unveraendert."
                    ),
                )
                return HttpResponseRedirect(reverse("admin:hr_schoolholiday_changelist"))

        if request.method == "POST" and import_action == "import_all_holidays":
            if selected_calendar is None:
                debug_info.append("import_all_holidays=aborted:no_calendar")
                self.message_user(request, "Bitte zuerst einen Feiertagskalender auswaehlen.", level=messages.ERROR)
            else:
                public_result = service.import_public_holidays(calendar=selected_calendar, holidays=public_holidays)
                school_result = service.import_school_holidays(calendar=selected_calendar, holidays=school_holidays)
                debug_info.append(
                    "import_all_holidays="
                    f"public(created:{public_result['created']} updated:{public_result['updated']} unchanged:{public_result['unchanged']}) "
                    f"school(created:{school_result['created']} updated:{school_result['updated']} unchanged:{school_result['unchanged']})"
                )
                logger.info("OpenHolidays combined import result: %s", debug_info[-1])
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
                return HttpResponseRedirect(reverse("admin:hr_publicholiday_changelist"))

        if request.method == "POST" and not import_action:
            debug_info.append("import_skipped=no_import_action")
            self.message_user(
                request,
                "Kein Importmodus erkannt. Bitte den Import-Button direkt anklicken.",
                level=messages.WARNING,
            )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "OpenHolidays Import",
            "subtitle": "Feiertage und Schulferien fuer das aktuelle Jahr laden und importieren",
            "form": form,
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
            "debug_info": debug_info,
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
    autocomplete_fields = ("employee", "schedule")

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
    readonly_fields = BaseAdmin.readonly_fields + ("calculated_days",)
    list_display = (
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "calculated_days",
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
        service = LeaveService()
        if not self.can_manage(request):
            employee_profile = self.access_service.get_user_employee_profile(request.user)
            if employee_profile is None:
                raise ValidationError("Ohne Mitarbeiterprofil kann kein Urlaubsantrag gespeichert werden.")
            obj.employee = employee_profile
        obj.calculated_days = service.calculate_leave_days_for_request(obj)
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


@admin.register(VacationEntitlement)
class VacationEntitlementAdmin(HrScopedAdminMixin, BaseAdmin):
    manager_permission_name = "can_manage_master_data"
    list_display = ("employee", "year", "base_days", "carryover_days", "carryover_expires_on", "total_days_display", "created_at")
    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "employee__short_code",
    )
    list_filter = [
        ("employee__department", RelatedDropdownFilter),
        ("employee", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]

    @admin.display(description="Gesamt", ordering="base_days")
    def total_days_display(self, obj: VacationEntitlement) -> str:
        return f"{obj.total_days:.2f}"

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
