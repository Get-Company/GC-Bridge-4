from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextInputWidget

from django_celery_beat import admin as celery_admin
from django_celery_beat.admin import PeriodicTaskForm, TaskSelectWidget
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)


class BaseAdmin(UnfoldModelAdmin):
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


class BaseTabularInline(UnfoldTabularInline):
    readonly_fields = ("created_at", "updated_at")
    extra = 0


class BaseStackedInline(UnfoldStackedInline):
    readonly_fields = ("created_at", "updated_at")
    extra = 0


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, UnfoldModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, UnfoldModelAdmin):
    pass


admin.site.unregister(IntervalSchedule)
admin.site.unregister(PeriodicTask)
admin.site.unregister(CrontabSchedule)
admin.site.unregister(SolarSchedule)
admin.site.unregister(ClockedSchedule)

BasePeriodicTaskAdmin = getattr(celery_admin, "PeriodicTaskAdmin", admin.ModelAdmin)
BaseIntervalScheduleAdmin = getattr(celery_admin, "IntervalScheduleAdmin", admin.ModelAdmin)
BaseCrontabScheduleAdmin = getattr(celery_admin, "CrontabScheduleAdmin", admin.ModelAdmin)
BaseSolarScheduleAdmin = getattr(celery_admin, "SolarScheduleAdmin", admin.ModelAdmin)
BaseClockedScheduleAdmin = getattr(celery_admin, "ClockedScheduleAdmin", admin.ModelAdmin)


class UnfoldTaskSelectWidget(UnfoldAdminSelectWidget, TaskSelectWidget):
    pass


class UnfoldPeriodicTaskForm(PeriodicTaskForm):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["task"].widget = UnfoldAdminTextInputWidget()
        self.fields["regtask"].widget = UnfoldTaskSelectWidget()


@admin.register(PeriodicTask)
class PeriodicTaskAdmin(BasePeriodicTaskAdmin):
    form = UnfoldPeriodicTaskForm


@admin.register(IntervalSchedule)
class IntervalScheduleAdmin(BaseIntervalScheduleAdmin):
    pass


@admin.register(CrontabSchedule)
class CrontabScheduleAdmin(BaseCrontabScheduleAdmin):
    pass


@admin.register(SolarSchedule)
class SolarScheduleAdmin(BaseSolarScheduleAdmin):
    pass


@admin.register(ClockedSchedule)
class ClockedScheduleAdmin(BaseClockedScheduleAdmin):
    pass
