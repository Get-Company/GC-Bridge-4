from django.contrib import admin
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.urls import reverse

from core.admin import BaseAdmin, BaseTabularInline
from microtech.models import (
    MicrotechJob,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
    MicrotechSettings,
)


class SingletonAdmin(BaseAdmin):
    """Admin base for singleton models: the changelist redirects straight to the single edit form."""

    def changelist_view(self, request, extra_context=None):
        obj = self.model.load()
        url = reverse(
            f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
            args=(obj.pk,),
        )
        return HttpResponseRedirect(url)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MicrotechSettings)
class MicrotechSettingsAdmin(SingletonAdmin):
    fieldsets = (
        (
            "Verbindung",
            {
                "fields": ("mandant", "firma"),
            },
        ),
        (
            "Benutzer",
            {
                "fields": ("benutzer", "manual_benutzer"),
                "description": "Benutzer für automatische und manuelle Sync-Vorgänge.",
            },
        ),
        (
            "Vorgang-Standardwerte",
            {
                "fields": ("default_vorgangsart_id", "default_zahlungsart_id", "default_versandart_id"),
                "description": "Standard-IDs für neue Microtech-Bestellungen (Vorgänge).",
            },
        ),
    )


@admin.register(MicrotechOrderRule)
class MicrotechOrderRuleAdmin(BaseAdmin):
    class ConditionInline(BaseTabularInline):
        model = MicrotechOrderRuleCondition
        fields = (
            "is_active",
            "priority",
            "source_field",
            "operator",
            "expected_value",
        )
        extra = 0

    class ActionInline(BaseTabularInline):
        model = MicrotechOrderRuleAction
        fields = (
            "is_active",
            "priority",
            "target_field",
            "target_value",
        )
        extra = 0

    list_display = (
        "priority",
        "name",
        "is_active",
        "condition_logic",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("name",)
    list_filter = (
        "is_active",
        "condition_logic",
    )
    ordering = ("priority", "id")
    inlines = (ConditionInline, ActionInline)

    fieldsets = (
        (
            "Regel",
            {
                "fields": ("name", "is_active", "priority", "condition_logic"),
            },
        ),
        (
            "Bedingungen",
            {
                "fields": (),
                "description": (
                    "Bedingungen werden ausschliesslich ueber die Inline-Tabelle gepflegt. "
                    "Ohne aktive Bedingungen gilt die Regel als globaler Fallback."
                ),
            },
        ),
    )


@admin.register(MicrotechJob)
class MicrotechJobAdmin(BaseAdmin):
    list_display = (
        "id",
        "job_type",
        "status",
        "priority",
        "attempt",
        "max_retries",
        "run_after",
        "worker_id",
        "created_at",
    )
    list_filter = ("job_type", "status", "priority")
    search_fields = ("id", "correlation_id", "last_error", "worker_id")
    readonly_fields = (
        "job_type",
        "payload",
        "result",
        "attempt",
        "max_retries",
        "created_by",
        "run_after",
        "started_at",
        "finished_at",
        "worker_id",
        "correlation_id",
        "last_error",
        "created_at",
        "updated_at",
    )
    actions = ("requeue_failed_jobs", "cancel_queued_jobs")

    @admin.action(description="Ausgewaehlte FAILED Jobs erneut einreihen")
    def requeue_failed_jobs(self, request, queryset):
        candidates = queryset.filter(status=MicrotechJob.Status.FAILED)
        now = timezone.now()
        updated = candidates.update(
            status=MicrotechJob.Status.QUEUED,
            run_after=now,
            finished_at=None,
            worker_id="",
            last_error="",
        )
        self.message_user(request, f"{updated} Job(s) erneut eingereiht.")

    @admin.action(description="Ausgewaehlte QUEUED Jobs abbrechen")
    def cancel_queued_jobs(self, request, queryset):
        now = timezone.now()
        updated = queryset.filter(status=MicrotechJob.Status.QUEUED).update(
            status=MicrotechJob.Status.CANCELLED,
            finished_at=now,
        )
        self.message_user(request, f"{updated} Job(s) abgebrochen.")
