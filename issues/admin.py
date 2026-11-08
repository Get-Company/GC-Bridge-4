from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from issues.models import ArchivedIssue, DEFAULT_ASSIGNED_USER_ID, Issue, IssueAttachment, IssueCategory, IssueMessage


ARCHIVED_ISSUE_STATUSES = (Issue.Status.RESOLVED, Issue.Status.CLOSED)


class StaffIssueAccessMixin:
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff


class IssueAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None and "error_text" in self.fields:
            self.fields["error_text"].label = "Erste Nachricht / Fehlertext"
            self.fields["error_text"].help_text = (
                "Optional. Dieser Text erscheint nach dem Speichern als erste Nachricht im Verlauf."
            )

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


class IssueReplyForm(forms.Form):
    text = forms.CharField(max_length=10000, strip=True)
    quote = forms.CharField(required=False)


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
    change_form_template = "admin/issues/issue/change_form.html"
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
        "messages__text",
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

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            return fieldsets
        return tuple(
            (
                title,
                {
                    **options,
                    "fields": tuple(field for field in options["fields"] if field != "error_text"),
                },
            )
            for title, options in fieldsets
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/reply/",
                self.admin_site.admin_view(self.reply_view),
                name=f"{self.opts.app_label}_{self.opts.model_name}_reply",
            ),
        ]
        return custom_urls + urls

    @staticmethod
    def _author_name(user):
        return (user.get_full_name() or user.get_username()) if user else "System"

    def _can_reply(self, request, obj):
        return self.has_change_permission(request, obj) and (
            request.user.is_superuser
            or request.user.pk in (obj.reported_by_id, obj.assigned_to_id)
        )

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj is not None:
            entries = []
            all_messages = list(
                obj.messages.select_related("author", "quoted_message__author")
            )
            initial_message = next(
                (message for message in all_messages if message.is_initial), None
            )
            for message in all_messages:
                quoted = initial_message if message.quotes_initial else message.quoted_message
                if quoted is not None:
                    quoted_text = quoted.text
                    quoted_author = self._author_name(quoted.author)
                else:
                    quoted_text = quoted_author = None
                entries.append(
                    {
                        "quote_key": str(message.pk),
                        "text": message.text,
                        "author": self._author_name(message.author),
                        "created_at": message.created_at,
                        "is_own": message.author_id == request.user.pk,
                        "quoted_text": quoted_text,
                        "quoted_author": quoted_author,
                    }
                )
            context.update(
                chat_entries=entries,
                can_reply=self._can_reply(request, obj),
                reply_url=reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_reply",
                    args=[obj.pk],
                ),
            )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def reply_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        issue = self.get_object(request, object_id)
        if issue is None:
            raise PermissionDenied
        if not self._can_reply(request, issue):
            raise PermissionDenied

        redirect_url = reverse(
            f"admin:{self.opts.app_label}_{self.opts.model_name}_change", args=[issue.pk]
        ) + "#issue-chat"
        form = IssueReplyForm(request.POST)
        if not form.is_valid():
            self.message_user(request, "Bitte eine Nachricht mit höchstens 10.000 Zeichen eingeben.", messages.ERROR)
            return HttpResponseRedirect(redirect_url)

        quote_key = form.cleaned_data["quote"]
        quoted_message = None
        if quote_key == "initial":
            quoted_message = issue.messages.filter(is_initial=True).first()
            if quoted_message is None:
                self.message_user(request, "Die zitierte Nachricht ist nicht mehr vorhanden.", messages.ERROR)
                return HttpResponseRedirect(redirect_url)
        elif quote_key:
            if not quote_key.isdecimal():
                self.message_user(request, "Die zitierte Nachricht ist ungültig.", messages.ERROR)
                return HttpResponseRedirect(redirect_url)
            quoted_message = issue.messages.filter(pk=quote_key).first()
            if quoted_message is None:
                self.message_user(request, "Die zitierte Nachricht gehört nicht zu diesem Issue.", messages.ERROR)
                return HttpResponseRedirect(redirect_url)

        IssueMessage.objects.create(
            issue=issue,
            author=request.user,
            text=form.cleaned_data["text"],
            quoted_message=quoted_message,
        )
        self.message_user(request, "Nachricht gesendet.", messages.SUCCESS)
        return HttpResponseRedirect(redirect_url)

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
