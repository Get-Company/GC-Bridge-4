from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from hr.forms import EmployeeProfileAdminForm, WorkScheduleDayInlineForm
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
    CalendarService,
    HolidayService,
    HrSetupService,
    LeaveService,
    MonthlySummaryService,
    OpenHolidaysService,
    TimeAccountService,
    WorkingTimeService,
)
from unfold.widgets import UnfoldAdminColorInputWidget, UnfoldAdminTimeWidget


class HrServiceUtilityTest(SimpleTestCase):
    def test_get_days_in_month_returns_all_dates(self):
        days = WorkingTimeService.get_days_in_month(2026, 2)

        self.assertEqual(days[0], date(2026, 2, 1))
        self.assertEqual(days[-1], date(2026, 2, 28))
        self.assertEqual(len(days), 28)

    def test_leave_day_units_handle_half_days(self):
        units = LeaveService.get_leave_day_units(
            start_date=date(2026, 5, 12),
            end_date=date(2026, 5, 14),
            half_day_start=True,
            half_day_end=False,
        )

        self.assertEqual(units, Decimal("2.5"))

    def test_time_account_split_minutes_separates_positive_and_negative_values(self):
        overtime_minutes, minus_minutes = TimeAccountService.split_minutes(
            [
                SimpleNamespace(minutes=60),
                SimpleNamespace(minutes=-30),
                SimpleNamespace(minutes=15),
                SimpleNamespace(minutes=-120),
            ]
        )

        self.assertEqual(overtime_minutes, 75)
        self.assertEqual(minus_minutes, -150)

    def test_monthly_balance_uses_positive_and_negative_time_account_values(self):
        balance = MonthlySummaryService.build_balance_minutes(
            overtime_minutes=120,
            minus_minutes=-45,
        )

        self.assertEqual(balance, 75)

    def test_leave_status_transition_rejects_invalid_change(self):
        with self.assertRaises(ValidationError):
            LeaveService.validate_status_transition(
                LeaveRequest.Status.APPROVED,
                LeaveRequest.Status.REQUESTED,
            )

    def test_time_account_status_transition_rejects_invalid_change(self):
        with self.assertRaises(ValidationError):
            TimeAccountService.validate_status_transition(
                TimeAccountEntry.Status.APPROVED,
                TimeAccountEntry.Status.REQUESTED,
            )

    def test_calendar_event_contains_visibility_fields(self):
        event = CalendarService._build_event(
            employee=SimpleNamespace(
                pk=12,
                short_code="FB",
                color="#123456",
                full_name="Fiona Beispiel",
                department_id=9,
                department=SimpleNamespace(name="Vertrieb"),
            ),
            title_suffix="Urlaub",
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 12),
            event_type="vacation",
        )

        self.assertEqual(event["employee_id"], 12)
        self.assertEqual(event["department"], "Vertrieb")
        self.assertTrue(event["allDay"])

    def test_global_calendar_event_does_not_require_employee(self):
        event = CalendarService._build_event(
            employee=None,
            title_suffix="Feiertag: Tag der Arbeit",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            event_type="public_holiday",
            color="#475569",
        )

        self.assertEqual(event["employee"], "")
        self.assertEqual(event["short_code"], "")
        self.assertEqual(event["type"], "public_holiday")

    def test_holiday_overlap_helper_detects_intersection(self):
        self.assertTrue(
            HolidayService.overlaps(
                start_date=date(2026, 5, 10),
                end_date=date(2026, 5, 12),
                other_start_date=date(2026, 5, 12),
                other_end_date=date(2026, 5, 14),
            )
        )

    def test_openholidays_extracts_localized_name(self):
        name = OpenHolidaysService._extract_localized_name(
            [
                {"language": "EN", "text": "New Year"},
                {"language": "DE", "text": "Neujahr"},
            ],
            language_iso_code="DE",
        )

        self.assertEqual(name, "Neujahr")

    def test_openholidays_normalizes_public_holiday_payload(self):
        service = OpenHolidaysService()

        with patch.object(
            service,
            "_request",
            return_value=[
                {
                    "startDate": "2026-01-01",
                    "name": [{"language": "DE", "text": "Neujahr"}],
                    "temporalScope": "FullDay",
                    "subdivisions": [{"code": "DE-BY"}],
                    "nationwide": False,
                }
            ],
        ):
            holidays = service.fetch_public_holidays(
                year=2026,
                country_iso_code="DE",
                language_iso_code="DE",
                subdivision_code="DE-BY",
            )

        self.assertEqual(len(holidays), 1)
        self.assertEqual(holidays[0]["date"], date(2026, 1, 1))
        self.assertEqual(holidays[0]["name"], "Neujahr")
        self.assertEqual(holidays[0]["subdivisions"], "DE-BY")
        self.assertFalse(
            HolidayService.overlaps(
                start_date=date(2026, 5, 10),
                end_date=date(2026, 5, 11),
                other_start_date=date(2026, 5, 12),
                other_end_date=date(2026, 5, 14),
            )
        )

    def test_openholidays_normalizes_school_holiday_payload(self):
        service = OpenHolidaysService()

        with patch.object(
            service,
            "_request",
            return_value=[
                {
                    "startDate": "2026-08-03",
                    "endDate": "2026-09-14",
                    "name": [{"language": "DE", "text": "Sommerferien"}],
                    "subdivisions": [{"code": "DE-BY"}],
                }
            ],
        ):
            holidays = service.fetch_school_holidays(
                year=2026,
                country_iso_code="DE",
                language_iso_code="DE",
                subdivision_code="DE-BY",
            )

        self.assertEqual(len(holidays), 1)
        self.assertEqual(holidays[0]["start_date"], date(2026, 8, 3))
        self.assertEqual(holidays[0]["end_date"], date(2026, 9, 14))
        self.assertEqual(holidays[0]["name"], "Sommerferien")

    def test_target_minutes_are_zeroed_on_holiday(self):
        employee = SimpleNamespace(start_date=None, end_date=None)
        service = WorkingTimeService()

        with patch.object(service, "get_scheduled_target_minutes_for_date", return_value=480), patch(
            "hr.services.working_time_service.HolidayService.is_non_working_holiday",
            return_value=True,
        ):
            target_minutes = service.get_target_minutes_for_date(employee, date(2026, 5, 1))

        self.assertEqual(target_minutes, 0)

    def test_calculate_leave_days_skips_non_working_days_and_respects_half_days(self):
        class StubWorkingTimeService:
            @staticmethod
            def get_target_minutes_for_date(employee, target_date):
                working_days = {
                    date(2026, 5, 4): 480,
                    date(2026, 5, 6): 480,
                }
                return working_days.get(target_date, 0)

        calculated_days = LeaveService().calculate_leave_days(
            SimpleNamespace(),
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 6),
            half_day_start=True,
            half_day_end=False,
            working_time_service=StubWorkingTimeService(),
        )

        self.assertEqual(calculated_days, Decimal("1.50"))


class HrAdminFormWidgetTest(SimpleTestCase):
    def test_employee_profile_form_uses_color_picker_widget(self):
        form = EmployeeProfileAdminForm()

        self.assertIsInstance(form.fields["color"].widget, UnfoldAdminColorInputWidget)
        self.assertEqual(form.fields["color"].widget.attrs.get("type"), "color")

    def test_work_schedule_day_form_uses_timepicker_widgets(self):
        form = WorkScheduleDayInlineForm()

        self.assertIsInstance(form.fields["start_time"].widget, UnfoldAdminTimeWidget)
        self.assertIsInstance(form.fields["end_time"].widget, UnfoldAdminTimeWidget)
        self.assertIn("core/admin/hr_work_schedule_time_fields.js", form.media.render_js())


class HrSetupServiceTest(TestCase):
    def test_ensure_groups_creates_expected_permissions(self):
        groups = HrSetupService.ensure_groups()

        self.assertSetEqual(
            set(groups.keys()),
            {
                AccessService.GROUP_EMPLOYEE,
                AccessService.GROUP_TEAM_LEAD,
                AccessService.GROUP_DEPARTMENT_LEAD,
                AccessService.GROUP_HR,
                AccessService.GROUP_MANAGEMENT,
            },
        )
        hr_group = Group.objects.get(name=AccessService.GROUP_HR)
        self.assertTrue(hr_group.permissions.filter(codename="view_employeeprofile").exists())
        self.assertTrue(hr_group.permissions.filter(codename="change_monthlyworksummary").exists())

    def test_hr_bootstrap_command_creates_demo_data(self):
        out = StringIO()

        call_command(
            "hr_bootstrap",
            demo_username="demo.hr",
            create_demo_user=True,
            demo_password="test-pass-123",
            with_sample_records=True,
            stdout=out,
        )

        user = get_user_model().objects.get(username="demo.hr")
        profile = EmployeeProfile.objects.get(user=user)
        self.assertTrue(user.is_staff)
        self.assertEqual(profile.department.name, "Allgemein")
        self.assertEqual(profile.holiday_calendar.name, "Deutschland")
        self.assertTrue(EmployeeWorkSchedule.objects.filter(employee=profile, schedule__name="Vollzeit 40h").exists())
        self.assertTrue(LeaveRequest.objects.filter(employee=profile).exists())
        self.assertTrue(SickLeave.objects.filter(employee=profile).exists())
        self.assertTrue(TimeAccountEntry.objects.filter(employee=profile).exists())
        self.assertTrue(MonthlyWorkSummary.objects.filter(employee=profile).exists())
        self.assertIn("HR-Bootstrap erfolgreich abgeschlossen.", out.getvalue())


class HrAccessServiceVisibilityTest(TestCase):
    def setUp(self):
        HrSetupService.ensure_groups()
        self.user_model = get_user_model()
        self.department_a = Department.objects.create(name="Vertrieb", code="V")
        self.department_b = Department.objects.create(name="Einkauf", code="E")
        self.calendar = HolidayCalendar.objects.create(name="Deutschland", region_code="DE", is_default=True)

    def _create_employee(self, username: str, *, department: Department) -> EmployeeProfile:
        user = self.user_model.objects.create_user(username=username, password="pass", is_staff=True)
        return EmployeeProfile.objects.create(
            user=user,
            department=department,
            holiday_calendar=self.calendar,
            short_code=username[:3].upper(),
        )

    def test_regular_employee_sees_only_own_profile(self):
        own_profile = self._create_employee("own-user", department=self.department_a)
        self._create_employee("other-user", department=self.department_a)

        visible_ids = set(AccessService().get_visible_employee_queryset(own_profile.user).values_list("id", flat=True))

        self.assertSetEqual(visible_ids, {own_profile.id})

    def test_department_lead_sees_only_profiles_in_own_department(self):
        lead_profile = self._create_employee("lead-user", department=self.department_a)
        same_department = self._create_employee("colleague-user", department=self.department_a)
        other_department = self._create_employee("external-user", department=self.department_b)
        lead_profile.user.groups.add(Group.objects.get(name=AccessService.GROUP_DEPARTMENT_LEAD))

        visible_ids = set(AccessService().get_visible_employee_queryset(lead_profile.user).values_list("id", flat=True))

        self.assertSetEqual(visible_ids, {lead_profile.id, same_department.id})
        self.assertNotIn(other_department.id, visible_ids)


class HrLeaveConflictTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="employee", password="pass", is_staff=True)
        self.department = Department.objects.create(name="HR", code="HR")
        self.calendar = HolidayCalendar.objects.create(name="Deutschland", region_code="DE", is_default=True)
        self.employee = EmployeeProfile.objects.create(
            user=self.user,
            department=self.department,
            holiday_calendar=self.calendar,
            short_code="EMP",
        )

    def test_approve_leave_request_rejects_overlap_with_sick_leave(self):
        SickLeave.objects.create(
            employee=self.employee,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 11),
        )
        leave_request = LeaveRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            status=LeaveRequest.Status.REQUESTED,
        )

        with self.assertRaises(ValidationError):
            LeaveService().approve_leave_request(leave_request, approved_by=self.user)


class HrVacationBalanceTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="vacation-user", password="pass", is_staff=True)
        self.department = Department.objects.create(name="HR", code="HR")
        self.calendar = HolidayCalendar.objects.create(name="Deutschland", region_code="DE", is_default=True)
        self.employee = EmployeeProfile.objects.create(
            user=self.user,
            department=self.department,
            holiday_calendar=self.calendar,
            short_code="VAC",
            vacation_days_per_year=Decimal("30.00"),
        )
        self.schedule = WorkSchedule.objects.create(name="Vollzeit", is_active=True)
        for weekday in range(5):
            WorkScheduleDay.objects.create(
                schedule=self.schedule,
                weekday=weekday,
                is_working_day=True,
                start_time="08:00",
                end_time="16:00",
                break_minutes=30,
                target_minutes=480,
            )
        for weekday in (5, 6):
            WorkScheduleDay.objects.create(
                schedule=self.schedule,
                weekday=weekday,
                is_working_day=False,
                target_minutes=0,
            )
        EmployeeWorkSchedule.objects.create(
            employee=self.employee,
            schedule=self.schedule,
            valid_from=date(2026, 1, 1),
        )

    def test_remaining_vacation_days_use_only_approved_vacation_requests(self):
        PublicHoliday.objects.create(
            calendar=self.calendar,
            name="Sonderfeiertag",
            date=date(2026, 5, 6),
            is_active=True,
        )
        LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=LeaveRequest.LeaveType.VACATION,
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 8),
            status=LeaveRequest.Status.APPROVED,
        )
        LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=LeaveRequest.LeaveType.VACATION,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            status=LeaveRequest.Status.REQUESTED,
        )
        LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=LeaveRequest.LeaveType.SPECIAL_LEAVE,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            status=LeaveRequest.Status.APPROVED,
        )

        approved_days = LeaveService().get_approved_vacation_days_for_year(self.employee, 2026)
        remaining_days = LeaveService().get_remaining_vacation_days_for_year(self.employee, 2026)

        self.assertEqual(approved_days, Decimal("4.00"))
        self.assertEqual(remaining_days, Decimal("26.00"))


class HrOpenHolidaysImportTest(TestCase):
    def setUp(self):
        self.calendar = HolidayCalendar.objects.create(name="Bayern", region_code="DE-BY", is_default=True)

    def test_import_school_holidays_creates_entries(self):
        result = OpenHolidaysService().import_school_holidays(
            calendar=self.calendar,
            holidays=[
                {
                    "name": "Sommerferien",
                    "start_date": date(2026, 8, 3),
                    "end_date": date(2026, 9, 14),
                    "subdivisions": "DE-BY",
                }
            ],
        )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["unchanged"], 0)
        self.assertTrue(
            SchoolHoliday.objects.filter(
                calendar=self.calendar,
                name="Sommerferien",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 9, 14),
                source_subdivisions="DE-BY",
            ).exists()
        )

    def test_admin_openholidays_import_creates_public_and_school_holidays(self):
        HrSetupService.ensure_groups()
        user = get_user_model().objects.create_user(
            username="hr-admin",
            password="pass",
            is_staff=True,
        )
        user.groups.add(Group.objects.get(name=AccessService.GROUP_HR))
        self.client.force_login(user)

        with patch(
            "hr.admin.OpenHolidaysService.fetch_public_holidays",
            return_value=[
                {
                    "date": date(2026, 1, 1),
                    "name": "Neujahr",
                    "is_half_day": False,
                    "subdivisions": "DE-BY",
                }
            ],
        ), patch(
            "hr.admin.OpenHolidaysService.fetch_school_holidays",
            return_value=[
                {
                    "name": "Sommerferien",
                    "start_date": date(2026, 8, 3),
                    "end_date": date(2026, 9, 14),
                    "subdivisions": "DE-BY",
                }
            ],
        ):
            response = self.client.post(
                reverse("admin:hr_publicholiday_openholidays"),
                data={
                    "calendar": self.calendar.pk,
                    "year": 2026,
                    "country_iso_code": "DE",
                    "subdivision_code": "DE-BY",
                    "language_iso_code": "DE",
                    "action": "import_all_holidays",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            PublicHoliday.objects.filter(
                calendar=self.calendar,
                date=date(2026, 1, 1),
                name="Neujahr",
            ).exists()
        )
        self.assertTrue(
            SchoolHoliday.objects.filter(
                calendar=self.calendar,
                name="Sommerferien",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 9, 14),
            ).exists()
        )

    def test_admin_openholidays_import_works_with_import_action_field(self):
        HrSetupService.ensure_groups()
        user = get_user_model().objects.create_user(
            username="hr-admin-action",
            password="pass",
            is_staff=True,
        )
        user.groups.add(Group.objects.get(name=AccessService.GROUP_HR))
        self.client.force_login(user)

        with patch(
            "hr.admin.OpenHolidaysService.fetch_public_holidays",
            return_value=[
                {
                    "date": date(2026, 5, 1),
                    "name": "Tag der Arbeit",
                    "is_half_day": False,
                    "subdivisions": "DE-BY",
                }
            ],
        ), patch(
            "hr.admin.OpenHolidaysService.fetch_school_holidays",
            return_value=[],
        ):
            response = self.client.post(
                reverse("admin:hr_publicholiday_openholidays"),
                data={
                    "calendar": self.calendar.pk,
                    "year": 2026,
                    "country_iso_code": "DE",
                    "subdivision_code": "DE-BY",
                    "language_iso_code": "DE",
                    "import_action": "import_public_holidays",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            PublicHoliday.objects.filter(
                calendar=self.calendar,
                date=date(2026, 5, 1),
                name="Tag der Arbeit",
            ).exists()
        )

    def test_approve_leave_request_rejects_overlap_with_company_holiday(self):
        CompanyHoliday.objects.create(
            name="Sommerpause",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            counts_as_vacation=False,
        )
        leave_request = LeaveRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
            status=LeaveRequest.Status.REQUESTED,
        )

        with self.assertRaises(ValidationError):
            LeaveService().approve_leave_request(leave_request, approved_by=self.user)
