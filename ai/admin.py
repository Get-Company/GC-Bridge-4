from __future__ import annotations

from django.contrib import admin

from core.admin import BaseAdmin

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(BaseAdmin):
    list_display = ("name", "model_name", "base_url", "is_active", "created_at")
    search_fields = ("name", "model_name", "base_url")
    list_filter = ("is_active",)


@admin.register(AIRewritePrompt)
class AIRewritePromptAdmin(BaseAdmin):
    list_display = ("name", "is_active", "created_at")
    search_fields = ("name", "slug")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AIRewriteJob)
class AIRewriteJobAdmin(BaseAdmin):
    list_display = ("__str__", "product", "field", "prompt", "provider", "status", "created_at")
    search_fields = ("product__erp_nr", "product__name", "field", "prompt__name", "result_text")
    list_filter = ("status", "prompt", "provider", "created_at")
