from __future__ import annotations

from django import forms
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.views.generic import FormView
from unfold.views import UnfoldModelAdminViewMixin
from unfold.widgets import UnfoldAdminSelect2Widget

from core.admin import BaseAdmin

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.rewrite_fields import get_rewriteable_product_field_names
from ai.services import AIRewriteService
from ai.tasks import run_ai_rewrite_job
from products.models import Product


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

    def __init__(self, *args, product=None, field="", **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        self.field_name = field

    def clean(self):
        cleaned = super().clean()
        if self.product is None:
            raise forms.ValidationError("Kein gueltiges Produkt uebergeben.")
        if self.field_name not in get_rewriteable_product_field_names():
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

    def _get_field(self):
        return self.request.GET.get("field") or self.request.POST.get("field") or ""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["product"] = self._get_product()
        kwargs["field"] = self._get_field()
        return kwargs

    def form_valid(self, form):
        job = AIRewriteService().create_job(
            product=form.product,
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
        context.update({
            "product": self._get_product(),
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
    list_display = ("__str__", "product", "field", "prompt", "provider", "status", "created_at")
    search_fields = ("product__erp_nr", "product__name", "field", "prompt__name", "result_text")
    list_filter = ("status", "prompt", "provider", "created_at")

    def get_urls(self):
        create_view = self.admin_site.admin_view(
            AIRewriteJobCreateView.as_view(model_admin=self)
        )
        return [
            path("new/", create_view, name="ai_airewritejob_create"),
        ] + super().get_urls()
