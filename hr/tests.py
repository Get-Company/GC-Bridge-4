from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from hr.models import LeaveRequest, TimeAccountEntry
from hr.services import (
    CalendarService,
    HolidayService,
    LeaveService,
    MonthlySummaryService,
    TimeAccountService,
    WorkingTimeService,
)


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
        self.assertFalse(
            HolidayService.overlaps(
                start_date=date(2026, 5, 10),
                end_date=date(2026, 5, 11),
                other_start_date=date(2026, 5, 12),
                other_end_date=date(2026, 5, 14),
            )
        )

    def test_target_minutes_are_zeroed_on_holiday(self):
        employee = SimpleNamespace(start_date=None, end_date=None)
        service = WorkingTimeService()

        with patch.object(service, "get_scheduled_target_minutes_for_date", return_value=480), patch(
            "hr.services.working_time_service.HolidayService.is_non_working_holiday",
            return_value=True,
        ):
            target_minutes = service.get_target_minutes_for_date(employee, date(2026, 5, 1))

        self.assertEqual(target_minutes, 0)
