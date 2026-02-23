from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db import models

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm


class BaseAdmin(UnfoldModelAdmin):
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    compressed_fields = True
    warn_unsaved_form = True
    change_form_show_cancel_button = True
    list_filter_sheet = True
    list_filter_submit = True
    list_horizontal_scrollbar_top = True
    formfield_overrides = {
        models.TextField: {"widget": WysiwygWidget},
    }


class BaseTabularInline(UnfoldTabularInline):
    readonly_fields = ("created_at", "updated_at")
    extra = 0
    tab = True
    formfield_overrides = BaseAdmin.formfield_overrides


class BaseStackedInline(UnfoldStackedInline):
    readonly_fields = ("created_at", "updated_at")
    extra = 0
    tab = True
    formfield_overrides = BaseAdmin.formfield_overrides


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
