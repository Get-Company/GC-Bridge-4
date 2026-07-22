from datetime import timedelta
from urllib.parse import urlencode

from celery import current_app
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.contrib.admin.utils import quote
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import models
from django.forms.models import model_to_dict
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.decorators import action
from unfold.enums import ActionVariant
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextInputWidget

from django_celery_beat.admin import (
    ClockedScheduleAdmin as BeatClockedScheduleAdmin,
    CrontabScheduleAdmin as BeatCrontabScheduleAdmin,
    IntervalScheduleAdmin as BeatIntervalScheduleAdmin,
    PeriodicTaskAdmin as BeatPeriodicTaskAdmin,
    PeriodicTaskForm as BeatPeriodicTaskForm,
    PeriodicTaskInline as BeatPeriodicTaskInline,
    ScheduleAdmin as BeatScheduleAdmin,
    SolarScheduleAdmin as BeatSolarScheduleAdmin,
    TaskSelectWidget as BeatTaskSelectWidget,
)
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)

from core.admin_status import admin_status_bar_api
from core.live_events_view import live_events_api, live_events_detail_api, live_events_view
from core.log_reader import get_allowed_log_files, log_file_info, search_log_file, tail_log_file
from core.microtech_queue_view import microtech_queue_api, microtech_queue_view
from core.services import CommandRuntimeService
from core.system_status_view import system_status_api, system_status_view
from microtech.views.connection import microtech_connection_admin_view
from hr.views import hr_calendar_api, hr_calendar_view
from customer.views import (
    customer_merge_view,
    customer_merge_resolve_api,
    customer_merge_search_cell_api,
    customer_merge_search_api,
    customer_merge_execute_api,
    customer_update_ids_api,
    customer_delete_addresses_api,
    customer_sync_direction_api,
)


class SortableAdminMixin:
    """Enable Unfold sorting for conventionally named, safe ordering fields.

    A sortable field must meet Unfold's requirements: it is a positive integer,
    indexed, and already part of the declared ordering. This keeps sorting
    opt-in at the model level while eliminating repeated admin configuration.
    """

    sortable_field_names = ("sort_order", "order", "position")
    hide_ordering_field = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_default_sorting()

    def _configure_default_sorting(self) -> None:
        if self.ordering_field:
            return

        declared_ordering = self.__class__.__dict__.get("ordering")
        uses_model_ordering = declared_ordering is None
        ordering = self.model._meta.ordering if uses_model_ordering else declared_ordering

        for field_name in self.sortable_field_names:
            try:
                field = self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue

            if not isinstance(field, (models.PositiveIntegerField, models.PositiveSmallIntegerField)):
                continue
            if not field.db_index or field_name in self.readonly_fields:
                continue
            if not self._ordering_includes_field(ordering, field_name):
                continue

            self.ordering_field = field_name
            self._uses_model_sortable_ordering = uses_model_ordering
            return

    @staticmethod
    def _ordering_includes_field(ordering, field_name: str) -> bool:
        return any(str(value).lstrip("-") == field_name for value in ordering or ())


class BaseAdmin(SortableAdminMixin, UnfoldModelAdmin):
    base_actions_row = ("copy_admin_object_row", "delete_admin_object_row")
    copy_source_param = "_copy_from"
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

    def get_ordering(self, request):
        if getattr(self, "_uses_model_sortable_ordering", False):
            return self.model._meta.ordering
        return super().get_ordering(request)

    def _get_base_actions_row(self):
        action_names = list(self._extract_action_names(getattr(self, "actions_row", ())))

        for action_name in self.base_actions_row:
            if action_name not in action_names:
                action_names.append(action_name)

        return [self.get_unfold_action(action_name) for action_name in action_names]

    def _admin_url_name(self, action: str) -> str:
        return (
            f"{self.admin_site.name}:"
            f"{self.opts.app_label}_{self.opts.model_name}_{action}"
        )

    def _redirect_to_changelist(self) -> HttpResponseRedirect:
        return HttpResponseRedirect(reverse(self._admin_url_name("changelist")))

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        object_id = request.GET.get(self.copy_source_param)

        if not object_id:
            return initial

        initial.pop(self.copy_source_param, None)
        obj = self.get_object(request, object_id)

        if obj is None:
            self.message_user(
                request,
                _("Das zu kopierende Objekt wurde nicht gefunden."),
                level=messages.ERROR,
            )
            return initial

        if (
            not self.has_add_permission(request)
            or not self.has_view_or_change_permission(request, obj)
        ):
            raise PermissionDenied

        copy_initial = model_to_dict(obj)
        copy_initial.pop(self.opts.pk.name, None)
        copy_initial.pop(self.opts.pk.attname, None)

        return {**copy_initial, **initial}

    def has_copy_admin_object_row_permission(self, request):
        return (
            self.has_add_permission(request)
            and self.has_view_or_change_permission(request)
        )

    def has_delete_admin_object_row_permission(self, request):
        return self.has_delete_permission(request)

    @action(
        description=_("Kopieren"),
        icon="content_copy",
        permissions=("copy_admin_object_row",),
        url_path="copy",
        variant=ActionVariant.DEFAULT,
    )
    def copy_admin_object_row(self, request, object_id: str):
        obj = self.get_object(request, object_id)

        if obj is None:
            self.message_user(
                request,
                _("Das zu kopierende Objekt wurde nicht gefunden."),
                level=messages.ERROR,
            )
            return self._redirect_to_changelist()

        if (
            not self.has_add_permission(request)
            or not self.has_view_or_change_permission(request, obj)
        ):
            raise PermissionDenied

        url = reverse(self._admin_url_name("add"))
        query = urlencode({self.copy_source_param: str(obj.pk)})
        return HttpResponseRedirect(f"{url}?{query}")

    @action(
        description=_("Löschen"),
        icon="delete",
        permissions=("delete_admin_object_row",),
        url_path="delete-row",
        variant=ActionVariant.DANGER,
    )
    def delete_admin_object_row(self, request, object_id: str):
        obj = self.get_object(request, object_id)

        if obj is None:
            self.message_user(
                request,
                _("Das zu löschende Objekt wurde nicht gefunden."),
                level=messages.ERROR,
            )
            return self._redirect_to_changelist()

        if not self.has_delete_permission(request, obj):
            raise PermissionDenied

        url = reverse(self._admin_url_name("delete"), args=(quote(str(obj.pk)),))
        return HttpResponseRedirect(url)


class BaseTabularInline(SortableAdminMixin, UnfoldTabularInline):
    readonly_fields = ("created_at", "updated_at")
    extra = 0
    tab = True
    formfield_overrides = BaseAdmin.formfield_overrides


class BaseStackedInline(SortableAdminMixin, UnfoldStackedInline):
    readonly_fields = ("created_at", "updated_at")
    extra = 0
    tab = True
    formfield_overrides = BaseAdmin.formfield_overrides


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, BaseAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    readonly_fields = ()


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, BaseAdmin):
    readonly_fields = ()


class CeleryBeatPeriodicTaskInline(BeatPeriodicTaskInline, BaseTabularInline):
    readonly_fields = BeatPeriodicTaskInline.readonly_fields
    ordering = ("name",)


class CeleryBeatBaseAdmin(BaseAdmin):
    readonly_fields = ()
    ordering = ()


class CeleryBeatScheduleAdmin(BeatScheduleAdmin, CeleryBeatBaseAdmin):
    inlines = [CeleryBeatPeriodicTaskInline]


class CeleryBeatClockedScheduleAdmin(BeatClockedScheduleAdmin, CeleryBeatScheduleAdmin):
    pass


class CeleryBeatCrontabScheduleAdmin(BeatCrontabScheduleAdmin, CeleryBeatScheduleAdmin):
    readonly_fields = BeatCrontabScheduleAdmin.readonly_fields


class CeleryBeatSolarScheduleAdmin(BeatSolarScheduleAdmin, CeleryBeatScheduleAdmin):
    pass


class CeleryBeatIntervalScheduleAdmin(BeatIntervalScheduleAdmin, CeleryBeatScheduleAdmin):
    pass


class UnfoldTaskSelectWidget(UnfoldAdminSelectWidget, BeatTaskSelectWidget):
    pass


class _PeriodicTaskForm(BeatPeriodicTaskForm):
    def __init__(self, *args, **kwargs):
        current_app.autodiscover_tasks(force=True)
        super().__init__(*args, **kwargs)
        self.fields["task"].widget = UnfoldAdminTextInputWidget()
        self.fields["regtask"].widget = UnfoldTaskSelectWidget()
        for field_name in ("args", "kwargs", "headers"):
            self.fields[field_name].widget = forms.Textarea(attrs={"rows": 3})

    def clean_args(self):
        if not (self.cleaned_data.get("args") or "").strip():
            self.cleaned_data["args"] = "[]"
        return super().clean_args()

    def clean_kwargs(self):
        if not (self.cleaned_data.get("kwargs") or "").strip():
            self.cleaned_data["kwargs"] = "{}"
        return super().clean_kwargs()

    def clean_headers(self):
        if not (self.cleaned_data.get("headers") or "").strip():
            self.cleaned_data["headers"] = "{}"
        return self._clean_json("headers")


class CeleryBeatPeriodicTaskAdmin(BeatPeriodicTaskAdmin, CeleryBeatBaseAdmin):
    form = _PeriodicTaskForm
    readonly_fields = BeatPeriodicTaskAdmin.readonly_fields
    ordering = ("name",)


for model in (ClockedSchedule, CrontabSchedule, IntervalSchedule, PeriodicTask, SolarSchedule):
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass

admin.site.register(ClockedSchedule, CeleryBeatClockedScheduleAdmin)
admin.site.register(CrontabSchedule, CeleryBeatCrontabScheduleAdmin)
admin.site.register(IntervalSchedule, CeleryBeatIntervalScheduleAdmin)
admin.site.register(PeriodicTask, CeleryBeatPeriodicTaskAdmin)
admin.site.register(SolarSchedule, CeleryBeatSolarScheduleAdmin)


def _resolve_log_file(request) -> tuple[list, int, object | None]:
    from pathlib import Path as _Path
    file_options = get_allowed_log_files()
    try:
        selected_index = int(request.GET.get("file", "0") or "0")
    except (TypeError, ValueError):
        selected_index = 0
    selected_index = max(0, min(selected_index, len(file_options) - 1 if file_options else 0))
    selected_path = file_options[selected_index] if file_options else None
    return file_options, selected_index, selected_path


def admin_log_reader_view(request):
    file_options, selected_index, selected_path = _resolve_log_file(request)

    try:
        requested_lines = int(request.GET.get("lines", "200") or "200")
    except (TypeError, ValueError):
        requested_lines = 200
    requested_lines = max(10, min(requested_lines, 5000))

    query = request.GET.get("q", "").strip()
    use_regex = request.GET.get("regex", "") == "1"
    try:
        context_lines = int(request.GET.get("context", "3") or "3")
    except (TypeError, ValueError):
        context_lines = 3
    context_lines = max(0, min(context_lines, 20))

    log_lines: list[str] = []
    search_result: dict | None = None
    file_info: dict = {}

    if selected_path:
        file_info = log_file_info(selected_path)
        if query:
            search_result = search_log_file(
                selected_path, query,
                context_lines=context_lines,
                use_regex=use_regex,
            )
        else:
            log_lines = tail_log_file(selected_path, requested_lines)

    context = {
        **admin.site.each_context(request),
        "title": "Log Reader",
        "file_options": [
            {"index": i, "path": str(p), "name": p.name}
            for i, p in enumerate(file_options)
        ],
        "selected_file_index": selected_index,
        "selected_path": str(selected_path) if selected_path else "",
        "selected_name": selected_path.name if selected_path else "",
        "file_info": file_info,
        "line_count": requested_lines,
        "log_lines": log_lines,
        "file_exists": bool(selected_path and selected_path.exists()),
        "query": query,
        "use_regex": use_regex,
        "context_lines": context_lines,
        "search_result": search_result,
    }
    return TemplateResponse(request, "admin/log_reader.html", context)


def admin_log_search_api(request):
    from django.http import JsonResponse as _JsonResponse
    file_options, selected_index, selected_path = _resolve_log_file(request)
    query = request.GET.get("q", "").strip()
    use_regex = request.GET.get("regex", "") == "1"
    try:
        context_lines = int(request.GET.get("context", "3") or "3")
    except (TypeError, ValueError):
        context_lines = 3

    if not selected_path or not query:
        return _JsonResponse({"error": "Datei oder Suchbegriff fehlt", "matches": [], "total": 0, "shown": 0})

    result = search_log_file(selected_path, query, context_lines=context_lines, use_regex=use_regex)
    return _JsonResponse(result)


def admin_log_download_view(request):
    from django.http import FileResponse, Http404
    file_options, selected_index, selected_path = _resolve_log_file(request)
    if not selected_path or not selected_path.exists():
        raise Http404("Log-Datei nicht gefunden")
    response = FileResponse(
        selected_path.open("rb"),
        as_attachment=True,
        filename=selected_path.name,
        content_type="text/plain; charset=utf-8",
    )
    return response


_default_admin_get_urls = admin.site.get_urls


def _admin_get_urls():
    custom_urls = [
        path("status-bar/api/", admin.site.admin_view(admin_status_bar_api), name="core_status_bar_api"),
        path("live-events/", admin.site.admin_view(live_events_view), name="core_live_events"),
        path("live-events/api/", admin.site.admin_view(live_events_api), name="core_live_events_api"),
        path("live-events/detail/", admin.site.admin_view(live_events_detail_api), name="core_live_events_detail"),
        path("logs/", admin.site.admin_view(admin_log_reader_view), name="core_log_reader"),
        path("logs/search/", admin.site.admin_view(admin_log_search_api), name="core_log_search"),
        path("logs/download/", admin.site.admin_view(admin_log_download_view), name="core_log_download"),
        path("system/", admin.site.admin_view(system_status_view), name="core_system_status"),
        path("system/api/", admin.site.admin_view(system_status_api), name="core_system_status_api"),
        path("customer-merge/", admin.site.admin_view(customer_merge_view), name="customer_merge"),
        path("customer-merge/api/resolve/", admin.site.admin_view(customer_merge_resolve_api), name="customer_merge_resolve"),
        path("customer-merge/api/search-cell/", admin.site.admin_view(customer_merge_search_cell_api), name="customer_merge_search_cell"),
        path("customer-merge/api/search/", admin.site.admin_view(customer_merge_search_api), name="customer_merge_search"),
        path("customer-merge/api/merge/", admin.site.admin_view(customer_merge_execute_api), name="customer_merge_execute"),
        path("customer-merge/api/update-ids/", admin.site.admin_view(customer_update_ids_api), name="customer_merge_update_ids"),
        path("customer-merge/api/delete-addresses/", admin.site.admin_view(customer_delete_addresses_api), name="customer_merge_delete_addresses"),
        path("customer-merge/api/sync/", admin.site.admin_view(customer_sync_direction_api), name="customer_merge_sync"),
        path("hr/calendar/", admin.site.admin_view(hr_calendar_view), name="hr_calendar"),
        path("hr/calendar/api/", admin.site.admin_view(hr_calendar_api), name="hr_calendar_api"),
        path("microtech-queue/", admin.site.admin_view(microtech_queue_view), name="core_microtech_queue"),
        path("microtech-queue/api/", admin.site.admin_view(microtech_queue_api), name="core_microtech_queue_api"),
        path("microtech-connection/", admin.site.admin_view(microtech_connection_admin_view), name="core_microtech_connection"),
    ]
    return custom_urls + _default_admin_get_urls()


admin.site.get_urls = _admin_get_urls


from core.database_backup_admin import DatabaseBackupAdmin  # noqa: F401
