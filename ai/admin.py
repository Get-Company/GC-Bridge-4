from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.generic import FormView
from unfold.contrib.forms.widgets import WYSIWYG_CLASSES
from unfold.decorators import action
from unfold.views import UnfoldModelAdminViewMixin
from unfold.widgets import UnfoldAdminSelect2Widget

from core.admin import BaseAdmin

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.rewrite_fields import (
    get_rewriteable_category_field_names,
    get_rewriteable_product_field_names,
)
from ai.services import AIRewriteService
from ai.tasks import run_ai_rewrite_job
from products.models import Category, Product


class AIRewriteJobCreateForm(forms.Form):
    prompt = forms.ModelChoiceField(
        label="Prompt",
        queryset=AIRewritePrompt.objects.filter(is_active=True).order_by("name"),
        widget=UnfoldAdminSelect2Widget,
    )
    provider = forms.ModelChoiceField(
        label="KI",
        queryset=AIProviderConfig.objects.filter(is_active=True).order_by("name"),
        widget=UnfoldAdminSelect2Widget,
    )

    def __init__(self, *args, product=None, category=None, field="", **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        self.category = category
        self.field_name = field

    def clean(self):
        cleaned = super().clean()
        if (self.product is None) == (self.category is None):
            raise forms.ValidationError("Kein gueltiges Zielobjekt uebergeben.")
        allowed_fields = (
            get_rewriteable_product_field_names()
            if self.product is not None
            else get_rewriteable_category_field_names()
        )
        if self.field_name not in allowed_fields:
            raise forms.ValidationError("Dieses Feld kann nicht per KI umgeschrieben werden.")
        return cleaned


class AIRewriteJobCreateView(UnfoldModelAdminViewMixin, FormView):
    title = "AI Rewrite erzeugen"
    permission_required = ("ai.add_airewritejob",)
    template_name = "admin/ai/rewrite_job_create.html"
    form_class = AIRewriteJobCreateForm

    def _get_product(self):
        pk = self.request.GET.get("product") or self.request.POST.get("product")
        return Product.objects.filter(pk=pk).first() if pk else None

    def _get_category(self):
        pk = self.request.GET.get("category") or self.request.POST.get("category")
        return Category.objects.filter(pk=pk).first() if pk else None

    def _get_field(self):
        return (
            self.request.GET.get("field")
            or self.request.POST.get("field")
            or self.request.GET.get("target_field")
            or self.request.POST.get("target_field")
            or ""
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["product"] = self._get_product()
        kwargs["category"] = self._get_category()
        kwargs["field"] = self._get_field()
        return kwargs

    def form_valid(self, form):
        job = AIRewriteService().create_job(
            product=form.product,
            category=form.category,
            field=form.field_name,
            prompt=form.cleaned_data["prompt"],
            provider=form.cleaned_data["provider"],
            requested_by=self.request.user,
        )
        async_result = run_ai_rewrite_job.delay(job.pk)
        AIRewriteJob.objects.filter(pk=job.pk, celery_task_id="").update(
            celery_task_id=getattr(async_result, "id", "") or ""
        )
        return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self._get_product()
        category = self._get_category()
        target = product or category
        context.update({
            "product": product,
            "category": category,
            "target": target,
            "target_label": "Produkt" if product else "Kategorie" if category else "Zielobjekt",
            "field_name": self._get_field(),
            "changelist_url": reverse("admin:ai_airewritejob_changelist"),
        })
        return context


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
    list_display = ("__str__", "target_object", "field", "prompt", "provider", "status", "requested_by", "created_at")
    search_fields = (
        "product__erp_nr", "product__name", "category__name", "category__slug",
        "field", "prompt__name", "result_text",
    )
    list_filter = ("status", "prompt", "provider", "created_at")
    actions_detail = ("apply_rewrite_detail",)
    change_form_template = "admin/ai/airewritejob/change_form.html"
    readonly_fields = BaseAdmin.readonly_fields + (
        "target_object", "field", "prompt", "provider", "status",
        "source_snapshot_preview", "rendered_prompt", "error_message",
        "celery_task_id", "requested_by", "applied_at",
    )
    fieldsets = (
        ("Ergebnis", {
            "fields": ("status", "source_snapshot_preview", "result_text", "error_message"),
            "description": "Ergebnis pruefen, bei Bedarf bearbeiten und uebernehmen.",
        }),
        ("Kontext", {
            "fields": ("target_object", "field", "prompt", "provider", "rendered_prompt",
                       "celery_task_id", "requested_by", "applied_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_urls(self):
        create_view = self.admin_site.admin_view(
            AIRewriteJobCreateView.as_view(model_admin=self)
        )
        return [
            path("new/", create_view, name="ai_airewritejob_create"),
        ] + super().get_urls()

    @admin.display(description="Aktueller Quellinhalt")
    def source_snapshot_preview(self, obj: AIRewriteJob):
        value = obj.source_snapshot or "<p><em>Kein Inhalt.</em></p>"
        return format_html(
            '<div class="max-w-4xl relative"><div class="trix-content {}">{}</div></div>',
            " ".join(WYSIWYG_CLASSES), mark_safe(value),
        )

    @admin.display(description="Zielobjekt")
    def target_object(self, obj: AIRewriteJob):
        return obj.target

    @action(description="In Feld uebernehmen", icon="task_alt")
    def apply_rewrite_detail(self, request, object_id: str):
        job = self.get_object(request, object_id)
        if not job:
            self.message_user(request, "Rewrite-Job nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ai_airewritejob_changelist"))
        if job.status not in (AIRewriteJob.Status.READY, AIRewriteJob.Status.APPLIED):
            self.message_user(request, "Job hat noch kein Ergebnis.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
        try:
            AIRewriteService().apply(job=job)
        except Exception as exc:
            self.message_user(request, f"Konnte nicht uebernommen werden: {exc}", level=messages.ERROR)
        else:
            self.message_user(request, "Ergebnis wurde in das Zielfeld uebernommen.")
        return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
