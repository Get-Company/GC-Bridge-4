from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.contrib.forms.widgets import WYSIWYG_CLASSES
from unfold.decorators import action

from core.admin import BaseAdmin

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.services import AIRewriteApplyService, AIRewriteService
from products.models import Product


class ProductChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: Product) -> str:
        return f"{obj.erp_nr} · {obj.name}"


class PromptChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: AIRewritePrompt) -> str:
        return f"{obj.name} · {obj.target_field} · {obj.provider.name}"


class AIRewriteJobRequestForm(forms.Form):
    product = ProductChoiceField(
        label="Produkt",
        queryset=Product.objects.order_by("erp_nr"),
    )
    target_field = forms.ChoiceField(
        label="Zielfeld",
        choices=(),
    )
    prompt = PromptChoiceField(
        label="Prompt",
        queryset=AIRewritePrompt.objects.none(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        prompt_queryset = self._get_product_prompt_queryset()
        target_fields = list(prompt_queryset.values_list("target_field", flat=True).distinct())
        self.fields["target_field"].choices = [(field_name, field_name) for field_name in target_fields]

        target_field = self.data.get("target_field") or self.initial.get("target_field") or ""
        if target_field:
            prompt_queryset = prompt_queryset.filter(target_field=target_field)
        self.fields["prompt"].queryset = prompt_queryset

    def clean(self):
        cleaned_data = super().clean()
        prompt = cleaned_data.get("prompt")
        target_field = cleaned_data.get("target_field")
        if prompt is None or not target_field:
            return cleaned_data
        if prompt.target_field != target_field:
            self.add_error("prompt", "Der Prompt passt nicht zum ausgewaehlten Zielfeld.")
        return cleaned_data

    @staticmethod
    def _get_product_prompt_queryset():
        return AIRewritePrompt.objects.filter(
            is_active=True,
            content_type__app_label="products",
            content_type__model="product",
        ).select_related("provider").order_by("target_field", "name")


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
        "job_label",
        "product_link",
        "target_field",
        "prompt",
        "status",
        "is_archived",
        "requested_by",
        "approved_by",
        "created_at",
    )
    list_display_links = ("job_label",)
    search_fields = ("object_repr", "source_field", "target_field", "prompt__name", "result_text")
    list_filter = ("status", "is_archived", "prompt", "provider", "content_type", "created_at")
    actions = ("approve_selected", "approve_and_apply_selected", "reject_selected")
    actions_detail = ("apply_rewrite_detail",)
    readonly_fields = BaseAdmin.readonly_fields + (
        "job_label",
        "target_reference",
        "product_inline_preview",
        "current_target_preview",
    )
    fieldsets = (
        (
            "Freigabe",
            {
                "fields": (
                    "status",
                    "is_archived",
                    "current_target_preview",
                    "result_text",
                    "error_message",
                ),
                "classes": ("tab",),
                "description": "Aktuellen Feldinhalt gegen den neuen Rewrite pruefen und dann uebernehmen.",
            },
        ),
        (
            "Produkt",
            {
                "fields": (
                    "target_reference",
                    "product_inline_preview",
                ),
                "classes": ("tab",),
                "description": "Zielobjekt und die wichtigsten Produktinformationen zum Rewrite-Job.",
            },
        ),
        (
            "Prompt",
            {
                "fields": (
                    "prompt",
                    "provider",
                    "source_field",
                    "target_field",
                    "rendered_prompt",
                ),
                "classes": ("tab",),
                "description": "Verwendeter Prompt und die Feldzuordnung fuer diesen Rewrite-Job.",
            },
        ),
        (
            "Metadaten",
            {
                "fields": (
                    "requested_by",
                    "approved_by",
                    "approved_at",
                    "applied_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("tab",),
                "description": "Zeitstempel und Benutzerinformationen zum Freigabeprozess.",
            },
        ),
    )

    def get_urls(self):
        return [
            path(
                "request/",
                self.admin_site.admin_view(self.request_rewrite_view),
                name="ai_airewritejob_request",
            ),
        ] + super().get_urls()

    def request_rewrite_view(self, request):
        initial = {
            "product": request.GET.get("product", ""),
            "target_field": request.GET.get("target_field", ""),
        }
        form = AIRewriteJobRequestForm(request.POST or None, initial=initial)
        if request.method == "POST" and form.is_valid():
            job = AIRewriteService().request_rewrite(
                content_object=form.cleaned_data["product"],
                prompt=form.cleaned_data["prompt"],
                requested_by=request.user,
            )
            if job.status == AIRewriteJob.Status.FAILED:
                self.message_user(
                    request,
                    f"Rewrite fehlgeschlagen: {job.error_message}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Rewrite-Job fuer {job.object_repr} / {job.target_field} erzeugt.",
                )
            change_url = reverse("admin:ai_airewritejob_change", args=(job.pk,))
            return HttpResponseRedirect(change_url)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "AI Rewrite erzeugen",
            "subtitle": "Produkt und feldgebundenen Prompt auswaehlen",
            "form": form,
            "media": self.media + form.media,
            "changelist_url": reverse("admin:ai_airewritejob_changelist"),
        }
        return TemplateResponse(request, "admin/ai/rewrite_job_request.html", context)

    @admin.display(description="Rewrite-Job")
    def job_label(self, obj: AIRewriteJob):
        return f"#{obj.pk} · {obj.object_repr or obj.content_type} · {obj.target_field}"

    @admin.display(description="Produkt")
    def product_link(self, obj: AIRewriteJob):
        return self.target_object_link(obj)

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

    @admin.display(description="Objekt")
    def target_reference(self, obj: AIRewriteJob):
        label = obj.object_repr or f"{obj.content_type}:{obj.object_id}"
        linked_object = self.target_object_link(obj)
        return format_html(
            '<div class="flex flex-col gap-1"><div>{}</div><div class="text-xs text-base-500">Objekt-ID: {}</div></div>',
            linked_object,
            obj.object_id,
        )

    @admin.display(description="Produkt")
    def product_inline_preview(self, obj: AIRewriteJob):
        product = obj.content_object
        if not isinstance(product, Product):
            return "Kein Produkt hinterlegt."

        first_image = product.first_image
        image_html = ""
        if first_image and first_image.url:
            image_html = format_html(
                '<img src="{}" loading="lazy" style="width:96px;height:96px;object-fit:cover;border-radius:8px;" />',
                first_image.url,
            )

        return format_html(
            """
            <div style="display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:start;max-width:1100px;">
              <div>{}</div>
              <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;">
                <div><strong>ERP-Nr.</strong><br>{}</div>
                <div><strong>SKU</strong><br>{}</div>
                <div><strong>Name</strong><br>{}</div>
                <div><strong>Status</strong><br>{}</div>
              </div>
            </div>
            """,
            image_html,
            product.erp_nr,
            product.sku or "—",
            product.name or "—",
            "Aktiv" if product.is_active else "Inaktiv",
        )

    @admin.display(description="Aktueller Feldinhalt")
    def current_target_preview(self, obj: AIRewriteJob):
        value = ""
        if obj.content_object is not None and hasattr(obj.content_object, obj.target_field):
            current_value = getattr(obj.content_object, obj.target_field, "")
            value = "" if current_value is None else str(current_value)
        if not value.strip():
            value = "<p><em>Kein Inhalt vorhanden.</em></p>"
        return format_html(
            '<div class="max-w-4xl relative"><div class="trix-content {}">{}</div></div>',
            " ".join(WYSIWYG_CLASSES),
            mark_safe(value),
        )

    @action(
        description="Text uebernehmen",
        icon="task_alt",
    )
    def apply_rewrite_detail(self, request, object_id: str):
        job = self.get_object(request, object_id)
        if not job:
            self.message_user(request, "Rewrite-Job nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ai_airewritejob_changelist"))
        try:
            AIRewriteApplyService().apply(job=job, approved_by=request.user)
        except Exception as exc:
            self.message_user(request, f"Rewrite konnte nicht uebernommen werden: {exc}", level=messages.ERROR)
        else:
            self.message_user(request, "Rewrite wurde in das Zielfeld uebernommen und archiviert.")
        return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))

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
