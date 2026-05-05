from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from core.services import BaseService
from hr.models import (
    CompanyHoliday,
    Department,
    EmployeeProfile,
    EmployeeWorkSchedule,
    HolidayCalendar,
    LeaveRequest,
    MonthlyWorkSummary,
    PublicHoliday,
    SickLeave,
    TimeAccountEntry,
    WorkSchedule,
    WorkScheduleDay,
)
from hr.services.access_service import AccessService
from hr.services.monthly_summary_service import MonthlySummaryService


class HrSetupService(BaseService):
    model = EmployeeProfile

    EMPLOYEE_GROUP_PERMISSIONS = {
        "hr.view_employeeprofile",
        "hr.view_leaverequest",
        "hr.add_leaverequest",
        "hr.change_leaverequest",
        "hr.delete_leaverequest",
        "hr.view_timeaccountentry",
        "hr.view_monthlyworksummary",
        "hr.view_publicholiday",
        "hr.view_companyholiday",
    }
    DEPARTMENT_LEAD_GROUP_PERMISSIONS = EMPLOYEE_GROUP_PERMISSIONS | {
        "hr.view_department",
        "hr.view_sickleave",
        "hr.view_workschedule",
        "hr.view_employeeworkschedule",
    }
    HR_GROUP_PERMISSIONS = {
        "hr.view_department",
        "hr.add_department",
        "hr.change_department",
        "hr.delete_department",
        "hr.view_holidaycalendar",
        "hr.add_holidaycalendar",
        "hr.change_holidaycalendar",
        "hr.delete_holidaycalendar",
        "hr.view_employeeprofile",
        "hr.add_employeeprofile",
        "hr.change_employeeprofile",
        "hr.delete_employeeprofile",
        "hr.view_publicholiday",
        "hr.add_publicholiday",
        "hr.change_publicholiday",
        "hr.delete_publicholiday",
        "hr.view_companyholiday",
        "hr.add_companyholiday",
        "hr.change_companyholiday",
        "hr.delete_companyholiday",
        "hr.view_workschedule",
        "hr.add_workschedule",
        "hr.change_workschedule",
        "hr.delete_workschedule",
        "hr.view_workscheduleday",
        "hr.add_workscheduleday",
        "hr.change_workscheduleday",
        "hr.delete_workscheduleday",
        "hr.view_employeeworkschedule",
        "hr.add_employeeworkschedule",
        "hr.change_employeeworkschedule",
        "hr.delete_employeeworkschedule",
        "hr.view_leaverequest",
        "hr.add_leaverequest",
        "hr.change_leaverequest",
        "hr.delete_leaverequest",
        "hr.view_sickleave",
        "hr.add_sickleave",
        "hr.change_sickleave",
        "hr.delete_sickleave",
        "hr.view_timeaccountentry",
        "hr.add_timeaccountentry",
        "hr.change_timeaccountentry",
        "hr.delete_timeaccountentry",
        "hr.view_monthlyworksummary",
        "hr.change_monthlyworksummary",
    }
    GROUP_PERMISSION_MAP = {
        AccessService.GROUP_EMPLOYEE: EMPLOYEE_GROUP_PERMISSIONS,
        AccessService.GROUP_TEAM_LEAD: DEPARTMENT_LEAD_GROUP_PERMISSIONS,
        AccessService.GROUP_DEPARTMENT_LEAD: DEPARTMENT_LEAD_GROUP_PERMISSIONS,
        AccessService.GROUP_HR: HR_GROUP_PERMISSIONS,
        AccessService.GROUP_MANAGEMENT: HR_GROUP_PERMISSIONS,
    }

    @classmethod
    def ensure_groups(cls) -> dict[str, Group]:
        groups: dict[str, Group] = {}
        for group_name, permission_names in cls.GROUP_PERMISSION_MAP.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            permissions = Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=[permission_name.split(".", 1)[1] for permission_name in permission_names],
            ).order_by("content_type__app_label", "codename")
            group.permissions.set(permissions)
            groups[group_name] = group
        return groups

    @staticmethod
    def ensure_default_department(*, name: str = "Allgemein", code: str = "ALL") -> Department:
        department, _ = Department.objects.get_or_create(
            name=name,
            defaults={"code": code, "is_active": True},
        )
        changed = False
        if department.code != code:
            department.code = code
            changed = True
        if not department.is_active:
            department.is_active = True
            changed = True
        if changed:
            department.full_clean()
            department.save()
        return department

    @staticmethod
    def ensure_default_holiday_calendar(*, name: str = "Deutschland", region_code: str = "DE") -> HolidayCalendar:
        calendar, _ = HolidayCalendar.objects.get_or_create(
            name=name,
            defaults={
                "region_code": region_code,
                "is_active": True,
                "is_default": True,
            },
        )
        changed = False
        if calendar.region_code != region_code:
            calendar.region_code = region_code
            changed = True
        if not calendar.is_active:
            calendar.is_active = True
            changed = True
        if not calendar.is_default:
            HolidayCalendar.objects.exclude(pk=calendar.pk).filter(is_default=True).update(is_default=False)
            calendar.is_default = True
            changed = True
        if changed:
            calendar.full_clean()
            calendar.save()
        return calendar

    @staticmethod
    def ensure_default_work_schedule(*, name: str = "Vollzeit 40h") -> WorkSchedule:
        schedule, _ = WorkSchedule.objects.get_or_create(
            name=name,
            defaults={
                "description": "Montag bis Freitag je 8 Stunden.",
                "is_active": True,
            },
        )
        changed = False
        if schedule.description != "Montag bis Freitag je 8 Stunden.":
            schedule.description = "Montag bis Freitag je 8 Stunden."
            changed = True
        if not schedule.is_active:
            schedule.is_active = True
            changed = True
        if changed:
            schedule.full_clean()
            schedule.save()

        weekday_defaults = {
            WorkScheduleDay.Weekday.MONDAY: (True, time(8, 0), time(17, 0), 60, 480),
            WorkScheduleDay.Weekday.TUESDAY: (True, time(8, 0), time(17, 0), 60, 480),
            WorkScheduleDay.Weekday.WEDNESDAY: (True, time(8, 0), time(17, 0), 60, 480),
            WorkScheduleDay.Weekday.THURSDAY: (True, time(8, 0), time(17, 0), 60, 480),
            WorkScheduleDay.Weekday.FRIDAY: (True, time(8, 0), time(17, 0), 60, 480),
            WorkScheduleDay.Weekday.SATURDAY: (False, None, None, 0, 0),
            WorkScheduleDay.Weekday.SUNDAY: (False, None, None, 0, 0),
        }
        for weekday, values in weekday_defaults.items():
            is_working_day, start_time, end_time, break_minutes, target_minutes = values
            day, _ = WorkScheduleDay.objects.get_or_create(
                schedule=schedule,
                weekday=weekday,
                defaults={
                    "is_working_day": is_working_day,
                    "start_time": start_time,
                    "end_time": end_time,
                    "break_minutes": break_minutes,
                    "target_minutes": target_minutes,
                },
            )
            changed = any(
                [
                    day.is_working_day != is_working_day,
                    day.start_time != start_time,
                    day.end_time != end_time,
                    day.break_minutes != break_minutes,
                    day.target_minutes != target_minutes,
                ]
            )
            if changed:
                day.is_working_day = is_working_day
                day.start_time = start_time
                day.end_time = end_time
                day.break_minutes = break_minutes
                day.target_minutes = target_minutes
                day.full_clean()
                day.save()
        return schedule

    @staticmethod
    def ensure_demo_employee(
        *,
        username: str,
        create_user: bool = False,
        password: str = "",
        department: Department,
        holiday_calendar: HolidayCalendar,
        schedule: WorkSchedule,
        start_date: date | None = None,
    ) -> tuple[EmployeeProfile, bool]:
        user_model = get_user_model()
        user = user_model.objects.filter(username=username).first()
        created_user = False
        if user is None:
            if not create_user:
                raise ValueError(f"Benutzer '{username}' existiert nicht. Verwende --create-demo-user.")
            user = user_model.objects.create_user(
                username=username,
                email=f"{username}@example.com",
                password=password or "change-me",
                is_staff=True,
            )
            created_user = True
        elif create_user and password:
            user.set_password(password)
            user.save(update_fields=["password"])

        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])

        employee_group = Group.objects.filter(name=AccessService.GROUP_EMPLOYEE).first()
        if employee_group is not None:
            user.groups.add(employee_group)

        short_code = "".join(part[:1].upper() for part in username.replace(".", " ").replace("-", " ").split())[:4]
        short_code = short_code or username[:4].upper()
        profile, _ = EmployeeProfile.objects.get_or_create(
            user=user,
            defaults={
                "employee_number": username.upper(),
                "department": department,
                "holiday_calendar": holiday_calendar,
                "short_code": short_code,
                "color": "#3788d8",
                "is_active_employee": True,
                "vacation_days_per_year": Decimal("30.00"),
                "start_date": start_date or date.today(),
            },
        )
        changed = False
        if profile.department_id != department.pk:
            profile.department = department
            changed = True
        if profile.holiday_calendar_id != holiday_calendar.pk:
            profile.holiday_calendar = holiday_calendar
            changed = True
        if not profile.short_code:
            profile.short_code = short_code
            changed = True
        if profile.start_date is None:
            profile.start_date = start_date or date.today()
            changed = True
        if changed:
            profile.full_clean()
            profile.save()

        assignment_start = start_date or profile.start_date or date.today()
        assignment, _ = EmployeeWorkSchedule.objects.get_or_create(
            employee=profile,
            schedule=schedule,
            valid_from=assignment_start,
            defaults={"valid_until": None},
        )
        if assignment.schedule_id != schedule.pk:
            assignment.schedule = schedule
            assignment.full_clean()
            assignment.save()

        return profile, created_user

    @staticmethod
    def ensure_sample_records(*, employee: EmployeeProfile) -> dict[str, int]:
        today = date.today()
        leave_request, _ = LeaveRequest.objects.get_or_create(
            employee=employee,
            leave_type=LeaveRequest.LeaveType.VACATION,
            start_date=today + timedelta(days=14),
            end_date=today + timedelta(days=16),
            defaults={
                "status": LeaveRequest.Status.REQUESTED,
                "reason": "Beispielantrag",
            },
        )
        time_entry, _ = TimeAccountEntry.objects.get_or_create(
            employee=employee,
            date=today - timedelta(days=1),
            entry_type=TimeAccountEntry.EntryType.EXTRA_WORK,
            defaults={
                "minutes": 60,
                "reason": "Beispiel Mehrarbeit",
                "status": TimeAccountEntry.Status.REQUESTED,
            },
        )
        sick_leave, _ = SickLeave.objects.get_or_create(
            employee=employee,
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=29),
            defaults={
                "has_certificate": False,
                "note": "Beispiel Krankmeldung",
            },
        )
        summary = MonthlySummaryService().recalculate_monthly_summary(employee, today.year, today.month)
        return {
            "leave_request_id": leave_request.pk,
            "time_account_entry_id": time_entry.pk,
            "sick_leave_id": sick_leave.pk,
            "monthly_summary_id": summary.pk,
        }

    def bootstrap(
        self,
        *,
        demo_username: str = "",
        create_demo_user: bool = False,
        demo_password: str = "",
        with_sample_records: bool = False,
    ) -> dict[str, object]:
        groups = self.ensure_groups()
        department = self.ensure_default_department()
        holiday_calendar = self.ensure_default_holiday_calendar()
        schedule = self.ensure_default_work_schedule()

        result: dict[str, object] = {
            "groups": list(groups.keys()),
            "department_id": department.pk,
            "holiday_calendar_id": holiday_calendar.pk,
            "work_schedule_id": schedule.pk,
        }
        if demo_username:
            profile, created_user = self.ensure_demo_employee(
                username=demo_username,
                create_user=create_demo_user,
                password=demo_password,
                department=department,
                holiday_calendar=holiday_calendar,
                schedule=schedule,
            )
            result["employee_profile_id"] = profile.pk
            result["created_demo_user"] = created_user
            if with_sample_records:
                result["samples"] = self.ensure_sample_records(employee=profile)
        return result
