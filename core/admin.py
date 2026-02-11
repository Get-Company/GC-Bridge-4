from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm


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
