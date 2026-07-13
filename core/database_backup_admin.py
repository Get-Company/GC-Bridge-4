from __future__ import annotations

from functools import partial

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin
from core.models import DatabaseBackup
from core.services import DatabaseBackupError, DatabaseBackupService
from core.tasks import create_database_backup, restore_database_backup


def _table_choices(table_names: list[str]) -> list[tuple[str, str]]:
    return [(table_name, table_name) for table_name in table_names]


class DatabaseBackupAdminForm(forms.ModelForm):
    table_names = forms.MultipleChoiceField(
        choices=(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Tabellen"),
        help_text=_("Ohne Auswahl wird die gesamte Datenbank gesichert."),
    )

    class Meta:
        model = DatabaseBackup
        fields = ("label", "table_names")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            selected_tables = DatabaseBackupService().validate_table_names(self.instance.table_names)
            self.fields["table_names"].choices = _table_choices(selected_tables)
            self.fields["table_names"].disabled = True
            return

        try:
            table_names = DatabaseBackupService().list_database_tables()
        except DatabaseBackupError as exc:
            table_names = []
            self.fields["table_names"].help_text = str(exc)
        self.fields["table_names"].choices = _table_choices(table_names)

    def clean_table_names(self) -> list[str]:
        return DatabaseBackupService().validate_table_names(self.cleaned_data["table_names"])


class RestoreDatabaseBackupForm(forms.Form):
    table_names = forms.MultipleChoiceField(
        choices=(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Tabellen"),
        help_text=_("Ohne Auswahl werden alle im Backup enthaltenen Tabellen wiederhergestellt."),
    )
    confirm_restore = forms.BooleanField(
        required=True,
        label=_("Wiederherstellung bestaetigen"),
    )

    def __init__(self, *args, table_names: list[str], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["table_names"].choices = _table_choices(table_names)

    def clean_table_names(self) -> list[str]:
        return DatabaseBackupService().validate_table_names(self.cleaned_data["table_names"])


@admin.register(DatabaseBackup)
class DatabaseBackupAdmin(BaseAdmin):
    form = DatabaseBackupAdminForm
    list_display = (
        "id",
        "label",
        "backup_scope",
        "status",
        "file_name",
        "file_size",
        "restore_status",
        "created_at",
    )
    list_filter = ("status", "restore_status", "created_at")
    search_fields = ("label", "file_name", "error_message", "restore_error_message")
    readonly_fields = BaseAdmin.readonly_fields + (
        "backup_scope",
        "status",
        "file_name",
        "file_size",
        "error_message",
        "started_at",
        "completed_at",
        "requested_by",
        "restore_status",
        "restore_scope",
        "restore_error_message",
        "restore_requested_by",
        "restore_started_at",
        "restore_completed_at",
    )
    actions_detail = (
        {
            "title": _("Backup"),
            "icon": "more_vert",
            "items": ["restore_database_backup_detail"],
        },
    )

    def has_module_permission(self, request) -> bool:
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    def has_add_permission(self, request) -> bool:
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    def has_restore_database_backup_permission(self, request, object_id=None) -> bool:
        return request.user.is_superuser

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (
                    _("Backup erstellen"),
                    {
                        "fields": ("label", "table_names"),
                    },
                ),
            )
        return (
            (
                _("Backup"),
                {
                    "fields": (
                        "label",
                        "backup_scope",
                        "status",
                        "file_name",
                        "file_size",
                        "error_message",
                        "requested_by",
                        "started_at",
                        "completed_at",
                    ),
                },
            ),
            (
                _("Wiederherstellung"),
                {
                    "fields": (
                        "restore_status",
                        "restore_scope",
                        "restore_error_message",
                        "restore_requested_by",
                        "restore_started_at",
                        "restore_completed_at",
                    ),
                },
            ),
            (
                _("System"),
                {
                    "fields": BaseAdmin.readonly_fields,
                },
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.readonly_fields + ("label", "table_names")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.requested_by = request.user
        super().save_model(request, obj, form, change)
        if not change:
            transaction.on_commit(partial(self._enqueue_backup, obj.pk))

    @admin.display(description=_("Umfang"))
    def backup_scope(self, obj: DatabaseBackup) -> str:
        table_names = DatabaseBackupService().validate_table_names(obj.table_names)
        return ", ".join(table_names) if table_names else _("Gesamte Datenbank")

    @admin.display(description=_("Dateigroesse"), ordering="file_size_bytes")
    def file_size(self, obj: DatabaseBackup) -> str:
        if not obj.file_size_bytes:
            return "-"
        size = float(obj.file_size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return "-"

    @admin.display(description=_("Wiederhergestellter Umfang"))
    def restore_scope(self, obj: DatabaseBackup) -> str:
        table_names = DatabaseBackupService().validate_table_names(obj.restore_table_names)
        return ", ".join(table_names) if table_names else _("Alle Tabellen dieses Backups")

    @action(
        description=_("Wiederherstellen"),
        icon="restore",
        variant=ActionVariant.DANGER,
        permissions=("restore_database_backup",),
    )
    def restore_database_backup_detail(self, request, object_id: str):
        backup = self.get_object(request, object_id)
        if backup is None:
            self.message_user(request, _("Backup nicht gefunden."), level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:core_databasebackup_changelist"))

        try:
            available_tables = DatabaseBackupService().restorable_table_names(backup)
        except DatabaseBackupError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:core_databasebackup_change", args=(backup.pk,)))

        if request.method == "POST":
            form = RestoreDatabaseBackupForm(request.POST, table_names=available_tables)
            if form.is_valid():
                try:
                    DatabaseBackupService().request_restore(
                        backup,
                        table_names=form.cleaned_data["table_names"],
                        requested_by=request.user,
                    )
                except DatabaseBackupError as exc:
                    form.add_error(None, str(exc))
                else:
                    transaction.on_commit(partial(self._enqueue_restore, backup.pk))
                    self.message_user(request, _("Wiederherstellung wurde eingereiht."))
                    return HttpResponseRedirect(reverse("admin:core_databasebackup_change", args=(backup.pk,)))
        else:
            form = RestoreDatabaseBackupForm(table_names=available_tables)

        context = {
            **self.admin_site.each_context(request),
            "title": _("Backup wiederherstellen"),
            "backup": backup,
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/core/databasebackup_restore.html", context)

    @staticmethod
    def _enqueue_backup(backup_id: int) -> None:
        try:
            create_database_backup.delay(backup_id)
        except Exception as exc:
            backup = DatabaseBackup.objects.get(pk=backup_id)
            backup.status = DatabaseBackup.Status.FAILED
            backup.error_message = f"Celery-Task konnte nicht eingereiht werden: {exc}"
            backup.completed_at = timezone.now()
            backup.save(update_fields=("status", "error_message", "completed_at", "updated_at"))

    @staticmethod
    def _enqueue_restore(backup_id: int) -> None:
        try:
            restore_database_backup.delay(backup_id)
        except Exception as exc:
            backup = DatabaseBackup.objects.get(pk=backup_id)
            backup.restore_status = DatabaseBackup.RestoreStatus.FAILED
            backup.restore_error_message = f"Celery-Task konnte nicht eingereiht werden: {exc}"
            backup.restore_completed_at = timezone.now()
            backup.save(
                update_fields=(
                    "restore_status",
                    "restore_error_message",
                    "restore_completed_at",
                    "updated_at",
                )
            )

    def delete_model(self, request, obj):
        self._delete_backup_file(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for backup in queryset:
            self._delete_backup_file(backup)
        super().delete_queryset(request, queryset)

    @staticmethod
    def _delete_backup_file(backup: DatabaseBackup) -> None:
        try:
            DatabaseBackupService().backup_path(backup).unlink(missing_ok=True)
        except DatabaseBackupError:
            pass
