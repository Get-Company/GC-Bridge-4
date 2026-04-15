from __future__ import annotations

from django.contrib import admin, messages
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

from core.admin import BaseAdmin

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.services import AIRewriteApplyService


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(BaseAdmin):
    list_display = ("name", "model_name", "base_url", "is_active", "created_at")
    search_fields = ("name", "model_name", "base_url")
    list_filter = ("is_active",)


@admin.register(AIRewritePrompt)
class AIRewritePromptAdmin(BaseAdmin):
    list_display = ("name", "content_model", "source_field", "target_field", "provider", "is_active", "created_at")
    search_fields = ("name", "slug", "source_field", "target_field", "provider__name")
    list_filter = ("is_active", "provider", "content_type")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Modell")
    def content_model(self, obj: AIRewritePrompt) -> str:
        model = obj.content_type.model_class()
        return model._meta.label if model else obj.content_type.model


@admin.register(AIRewriteJob)
class AIRewriteJobAdmin(BaseAdmin):
    list_display = (
        "target_object_link",
        "target_field",
        "prompt",
        "status",
        "requested_by",
        "approved_by",
        "created_at",
    )
    search_fields = ("object_repr", "source_field", "target_field", "prompt__name", "result_text")
    list_filter = ("status", "prompt", "provider", "content_type", "created_at")
    actions = ("approve_selected", "approve_and_apply_selected", "reject_selected")
    readonly_fields = BaseAdmin.readonly_fields + (
        "target_object_link",
        "source_preview",
        "result_preview",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "status",
                    "target_object_link",
                    "prompt",
                    "provider",
                    "source_field",
                    "target_field",
                    "requested_by",
                    "approved_by",
                    "approved_at",
                    "applied_at",
                )
            },
        ),
        (
            "Inhalt",
            {
                "fields": (
                    "source_preview",
                    "result_text",
                    "result_preview",
                    "rendered_prompt",
                    "error_message",
                )
            },
        ),
        (
            "Technisch",
            {
                "fields": (
                    "content_type",
                    "object_id",
                    "object_repr",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Objekt")
    def target_object_link(self, obj: AIRewriteJob):
        label = obj.object_repr or f"{obj.content_type}:{obj.object_id}"
        try:
            url = reverse(
                f"admin:{obj.content_type.app_label}_{obj.content_type.model}_change",
                args=(obj.object_id,),
            )
        except NoReverseMatch:
            return label
        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description="Quellinhalt")
    def source_preview(self, obj: AIRewriteJob):
        return format_html(
            '<div style="max-width: 1000px; white-space: pre-wrap;">{}</div>',
            obj.source_snapshot or "",
        )

    @admin.display(description="Ergebnis-Vorschau")
    def result_preview(self, obj: AIRewriteJob):
        return format_html(
            '<div style="max-width: 1000px; white-space: pre-wrap;">{}</div>',
            obj.result_text or "",
        )

    @admin.action(description="Freigeben")
    def approve_selected(self, request, queryset):
        service = AIRewriteApplyService()
        updated = 0
        for job in queryset:
            service.approve(job=job, approved_by=request.user)
            updated += 1
        self.message_user(request, f"{updated} Rewrite-Job(s) freigegeben.")

    @admin.action(description="Freigeben und uebernehmen")
    def approve_and_apply_selected(self, request, queryset):
        service = AIRewriteApplyService()
        applied = 0
        errors = 0
        for job in queryset:
            try:
                service.apply(job=job, approved_by=request.user)
                applied += 1
            except Exception as exc:
                errors += 1
                self.message_user(
                    request,
                    f"Rewrite-Job {job.pk} konnte nicht uebernommen werden: {exc}",
                    level=messages.ERROR,
                )
        if applied:
            self.message_user(request, f"{applied} Rewrite-Job(s) freigegeben und uebernommen.")
        if errors:
            self.message_user(request, f"{errors} Rewrite-Job(s) konnten nicht uebernommen werden.", level=messages.WARNING)

    @admin.action(description="Ablehnen")
    def reject_selected(self, request, queryset):
        service = AIRewriteApplyService()
        updated = 0
        for job in queryset:
            service.reject(job=job, approved_by=request.user)
            updated += 1
        self.message_user(request, f"{updated} Rewrite-Job(s) abgelehnt.")

