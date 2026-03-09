from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db import models
from datetime import timedelta
from django.template.response import TemplateResponse
from django.urls import path

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from core.log_reader import get_allowed_log_files, tail_log_file
from core.services import CommandRuntimeService
from core.system_status_view import system_status_api, system_status_run, system_status_view
from customer.views import (
    customer_merge_view,
    customer_merge_resolve_api,
    customer_merge_search_cell_api,
    customer_merge_search_api,
    customer_merge_execute_api,
    customer_update_ids_api,
    customer_sync_direction_api,
)


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


def admin_log_reader_view(request):
    runtime_entries = CommandRuntimeService().list_runs(include_stale=False, cleanup_stale=True)
    for entry in runtime_entries:
        entry["duration"] = str(timedelta(seconds=max(0, int(entry.get("age_seconds") or 0))))

    file_options = get_allowed_log_files()
    selected_file_index = request.GET.get("file", "0")
    lines = request.GET.get("lines", "50")

    try:
        selected_index = int(selected_file_index)
    except (TypeError, ValueError):
        selected_index = 0

    try:
        requested_lines = int(lines)
    except (TypeError, ValueError):
        requested_lines = 50
    requested_lines = max(10, min(requested_lines, 500))

    if file_options:
        selected_index = max(0, min(selected_index, len(file_options) - 1))
        selected_path = file_options[selected_index]
        log_lines = tail_log_file(selected_path, requested_lines)
    else:
        selected_path = None
        log_lines = []

    context = {
        **admin.site.each_context(request),
        "title": "Log Reader",
        "file_options": [
            {"index": index, "path": str(path)}
            for index, path in enumerate(file_options)
        ],
        "selected_file_index": selected_index,
        "selected_path": str(selected_path) if selected_path else "",
        "line_count": requested_lines,
        "log_lines": log_lines,
        "file_exists": bool(selected_path and selected_path.exists()),
        "runtime_entries": runtime_entries,
    }
    return TemplateResponse(request, "admin/log_reader.html", context)


_default_admin_get_urls = admin.site.get_urls


def _admin_get_urls():
    custom_urls = [
        path("logs/", admin.site.admin_view(admin_log_reader_view), name="core_log_reader"),
        path("system/", admin.site.admin_view(system_status_view), name="core_system_status"),
        path("system/api/", admin.site.admin_view(system_status_api), name="core_system_status_api"),
        path("system/run/", admin.site.admin_view(system_status_run), name="core_system_status_run"),
        path("customer-merge/", admin.site.admin_view(customer_merge_view), name="customer_merge"),
        path("customer-merge/api/resolve/", admin.site.admin_view(customer_merge_resolve_api), name="customer_merge_resolve"),
        path("customer-merge/api/search-cell/", admin.site.admin_view(customer_merge_search_cell_api), name="customer_merge_search_cell"),
        path("customer-merge/api/search/", admin.site.admin_view(customer_merge_search_api), name="customer_merge_search"),
        path("customer-merge/api/merge/", admin.site.admin_view(customer_merge_execute_api), name="customer_merge_execute"),
        path("customer-merge/api/update-ids/", admin.site.admin_view(customer_update_ids_api), name="customer_merge_update_ids"),
        path("customer-merge/api/sync/", admin.site.admin_view(customer_sync_direction_api), name="customer_merge_sync"),
    ]
    return custom_urls + _default_admin_get_urls()


admin.site.get_urls = _admin_get_urls
