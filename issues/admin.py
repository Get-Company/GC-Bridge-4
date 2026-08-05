from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.html import format_html
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from issues.models import ArchivedIssue, DEFAULT_ASSIGNED_USER_ID, Issue, IssueAttachment, IssueCategory


ARCHIVED_ISSUE_STATUSES = (Issue.Status.RESOLVED, Issue.Status.CLOSED)


class StaffIssueAccessMixin:
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff


class IssueAdminForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = "__all__"
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 7,
                    "placeholder": "Was ist passiert? Wo tritt es auf? Was waere erwartet?",
                }
            ),
            "error_text": forms.Textarea(
                attrs={
                    "class": "vLargeTextField font-mono",
                    "rows": 10,
                    "placeholder": "Fehlermeldung, Stacktrace oder Logauszug hier einfuegen.",
                    "spellcheck": "false",
                }
            ),
        }


class IssueAttachmentInline(StaffIssueAccessMixin, BaseTabularInline):
    model = IssueAttachment
    fields = ("attachment_type", "file", "caption", "created_at")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff


@admin.register(IssueCategory)
class IssueCategoryAdmin(StaffIssueAccessMixin, BaseAdmin):
    list_display = ("name", "color_preview", "is_active", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("name", "description")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Farbe")
    def color_preview(self, obj: IssueCategory):
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:6px;">'
            '<span style="display:inline-block;width:12px;height:12px;border-radius:999px;background:{};"></span>{}'
            "</span>",
            obj.color or "#64748b",
            obj.color or "-",
        )


@admin.register(Issue)
class IssueAdmin(StaffIssueAccessMixin, BaseAdmin):
    form = IssueAdminForm
    inlines = (IssueAttachmentInline,)
    list_display = (
        "title",
        "category",
        "status",
        "priority",
        "reported_by",
        "assigned_to",
        "source_link",
        "attachment_count",
        "created_at",
    )
    list_editable = ("priority", "assigned_to")
    list_filter = ("status", "priority", "category", "assigned_to", "created_at")
    search_fields = (
        "title",
        "description",
        "source_url",
        "error_text",
        "reported_by__username",
        "reported_by__first_name",
        "reported_by__last_name",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
    )
    readonly_fields = BaseAdmin.readonly_fields + (
        "reported_by",
        "source_link",
        "attachment_count",
        "resolved_at",
        "resolved_by",
    )
    _archived_state = False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self._archived_state:
            return queryset.filter(status__in=ARCHIVED_ISSUE_STATUSES)
        return queryset.exclude(status__in=ARCHIVED_ISSUE_STATUSES)

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    fieldsets = (
        (
            "Kurzmeldung",
            {
                "fields": (
                    "title",
                    "category",
                    "description",
                    "source_url",
                ),
                "description": "Pflicht ist nur die Kurzbeschreibung. Alles Weitere kann ergaenzt werden, wenn es hilft.",
            },
        ),
        (
            "Bearbeitung",
            {
                "fields": (
                    "status",
                    "priority",
                    "assigned_to",
                    "reported_by",
                ),
            },
        ),
        (
            "Fehlerdetails",
            {
                "fields": (
                    "error_text",
                    "error_file",
                    "source_link",
                    "attachment_count",
                ),
            },
        ),
        (
            "Abschlussdokumentation",
            {
                "fields": (
                    "resolution_note",
                    "resolved_at",
                    "resolved_by",
                ),
                "description": "Beim Status Erledigt oder Geschlossen muss kurz festgehalten werden, was gelöst wurde und warum. Zeitpunkt und Bearbeiter werden automatisch gespeichert.",
            },
        ),
        (
            "System",
            {
                "fields": BaseAdmin.readonly_fields,
                "classes": ("collapse",),
            },
        ),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assigned_to":
            kwargs["queryset"] = get_user_model().objects.filter(is_staff=True).order_by(
                "last_name",
                "first_name",
                "username",
            )
            kwargs["initial"] = DEFAULT_ASSIGNED_USER_ID
        elif db_field.name == "category":
            kwargs["queryset"] = IssueCategory.objects.filter(is_active=True).order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change and obj.reported_by_id is None and request.user.is_authenticated:
            obj.reported_by = request.user
        if obj.status in ARCHIVED_ISSUE_STATUSES and obj.resolved_at is None:
            obj.resolved_at = timezone.now()
            if request.user.is_authenticated:
                obj.resolved_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Link")
    def source_link(self, obj: Issue):
        if not obj.source_url:
            return "-"
        return format_html('<a href="{}" target="_blank" rel="noopener">Oeffnen</a>', obj.source_url)

    @admin.display(description="Anhaenge")
    def attachment_count(self, obj: Issue):
        if obj.pk is None:
            return 0
        return obj.attachments.count()


@admin.register(ArchivedIssue)
class ArchivedIssueAdmin(IssueAdmin):
    """Dedicated archive for issues with a terminal status."""

    _archived_state = True
    list_editable = ("priority", "assigned_to")
    actions = ("restore_issues",)
    actions_row = ("restore_issue_row",)
    actions_detail = (
        {
            "title": "Archiv",
            "icon": "unarchive",
            "items": ["restore_issue_detail"],
        },
    )

    def has_add_permission(self, request):
        return False

    @admin.action(description="Aus Archiv wiederherstellen")
    def restore_issues(self, request, queryset):
        restored = queryset.update(status=Issue.Status.IN_PROGRESS, updated_at=timezone.now())
        self.message_user(request, f"{restored} Issue(s) aus dem Archiv wiederhergestellt.")

    @action(
        description="Wiederherstellen",
        icon="unarchive",
        variant=ActionVariant.PRIMARY,
    )
    def restore_issue_row(self, request, object_id: str):
        issue = self.get_object(request, object_id)
        if issue is None:
            self.message_user(request, "Issue nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_changelist()
        self._restore_issue(issue)
        return self._redirect_to_working_issue_list()

    @action(
        description="Aus Archiv wiederherstellen",
        icon="unarchive",
        variant=ActionVariant.PRIMARY,
    )
    def restore_issue_detail(self, request, object_id: str):
        issue = self.get_object(request, object_id)
        if issue is None:
            self.message_user(request, "Issue nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_changelist()
        self._restore_issue(issue)
        return self._redirect_to_working_issue_list()

    def _restore_issue(self, issue: Issue) -> None:
        issue.status = Issue.Status.IN_PROGRESS
        issue.save(update_fields=("status", "updated_at"))

    @staticmethod
    def _redirect_to_working_issue_list():
        from django.http import HttpResponseRedirect
        from django.urls import reverse

        return HttpResponseRedirect(reverse("admin:issues_issue_changelist"))
