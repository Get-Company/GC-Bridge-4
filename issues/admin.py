from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from core.admin import BaseAdmin, BaseTabularInline
from issues.models import Issue, IssueAttachment, IssueCategory


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
    list_editable = ("status", "priority", "assigned_to")
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
    readonly_fields = BaseAdmin.readonly_fields + ("reported_by", "source_link", "attachment_count")

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
            kwargs["initial"] = 3
        elif db_field.name == "category":
            kwargs["queryset"] = IssueCategory.objects.filter(is_active=True).order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change and obj.reported_by_id is None and request.user.is_authenticated:
            obj.reported_by = request.user
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
