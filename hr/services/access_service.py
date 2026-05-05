from __future__ import annotations

from django.contrib.auth.models import AbstractUser

from core.services import BaseService
from hr.models import Department, EmployeeProfile


class AccessService(BaseService):
    model = EmployeeProfile

    GROUP_EMPLOYEE = "Mitarbeiter"
    GROUP_TEAM_LEAD = "Teamleitung"
    GROUP_HR = "Personalverwaltung"
    GROUP_DEPARTMENT_LEAD = "Abteilungsleitung"
    GROUP_MANAGEMENT = "Geschäftsführung"

    PRIVILEGED_GROUPS = {
        GROUP_HR,
        GROUP_MANAGEMENT,
    }
    DEPARTMENT_SCOPED_GROUPS = {
        GROUP_TEAM_LEAD,
        GROUP_DEPARTMENT_LEAD,
    }
    SICK_LEAVE_DETAIL_GROUPS = {
        GROUP_HR,
        GROUP_MANAGEMENT,
    }

    @staticmethod
    def get_user_employee_profile(user: AbstractUser) -> EmployeeProfile | None:
        if not getattr(user, "is_authenticated", False):
            return None
        try:
            return user.employee_profile
        except EmployeeProfile.DoesNotExist:
            return None

    @staticmethod
    def has_any_group(user: AbstractUser, group_names: set[str]) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        return user.groups.filter(name__in=group_names).exists()

    def can_view_all_employees(self, user: AbstractUser) -> bool:
        return self.has_any_group(user, self.PRIVILEGED_GROUPS)

    def can_view_department_employees(self, user: AbstractUser) -> bool:
        return self.has_any_group(user, self.DEPARTMENT_SCOPED_GROUPS)

    def can_view_calendar(self, user: AbstractUser) -> bool:
        return self.can_view_all_employees(user) or self.can_view_department_employees(user) or (
            self.get_user_employee_profile(user) is not None
        )

    def can_view_sick_leave_details(self, user: AbstractUser) -> bool:
        return self.has_any_group(user, self.SICK_LEAVE_DETAIL_GROUPS)

    def can_manage_master_data(self, user: AbstractUser) -> bool:
        return self.can_view_all_employees(user)

    def can_manage_leave_requests(self, user: AbstractUser) -> bool:
        return self.can_view_all_employees(user) or self.can_view_department_employees(user)

    def can_manage_sick_leaves(self, user: AbstractUser) -> bool:
        return self.can_view_all_employees(user)

    def can_manage_time_account(self, user: AbstractUser) -> bool:
        return self.can_view_all_employees(user)

    def can_manage_monthly_summaries(self, user: AbstractUser) -> bool:
        return self.can_view_all_employees(user)

    def get_visible_department_queryset(self, user: AbstractUser):
        if self.can_view_all_employees(user):
            return Department.objects.all()
        employee_profile = self.get_user_employee_profile(user)
        if employee_profile and employee_profile.department_id:
            return Department.objects.filter(pk=employee_profile.department_id)
        return Department.objects.none()

    def get_visible_employee_queryset(self, user: AbstractUser):
        queryset = self.get_queryset().select_related("user", "department")
        if self.can_view_all_employees(user):
            return queryset

        employee_profile = self.get_user_employee_profile(user)
        if employee_profile is None:
            return queryset.none()

        if self.can_view_department_employees(user) and employee_profile.department_id:
            return queryset.filter(department_id=employee_profile.department_id)

        return queryset.filter(pk=employee_profile.pk)

    def filter_queryset_for_user(self, user: AbstractUser, queryset, *, employee_field: str = "employee"):
        if self.can_view_all_employees(user):
            return queryset

        employee_profile = self.get_user_employee_profile(user)
        if employee_profile is None:
            return queryset.none()

        if self.can_view_department_employees(user) and employee_profile.department_id:
            return queryset.filter(**{f"{employee_field}__department_id": employee_profile.department_id})

        return queryset.filter(**{f"{employee_field}_id": employee_profile.pk})
