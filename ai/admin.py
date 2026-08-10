from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.generic import FormView
from unfold.contrib.forms.widgets import WYSIWYG_CLASSES
from unfold.decorators import action
from unfold.views import UnfoldModelAdminViewMixin
from unfold.widgets import UnfoldAdminSelect2Widget, UnfoldAdminTextareaWidget

from core.admin import BaseAdmin

from ai.models import (
    AIProviderConfig,
    AIRewriteJob,
    AIRewritePrompt,
    AITranslationConfig,
    AITranslationGlossaryEntry,
    AITranslationState,
)
from ai.rewrite_fields import (
    get_rewriteable_category_field_names,
    get_rewriteable_product_field_names,
)
from ai.services import AIRewriteService, AITranslationService
from ai.tasks import queue_ai_translation_scan, run_ai_rewrite_job, run_ai_translation_state
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
        if not self.is_bound:
            self.initial.setdefault("prompt", self.fields["prompt"].queryset.first())
            self.initial.setdefault("provider", self.fields["provider"].queryset.first())

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


class AIRewriteJobAdminForm(forms.ModelForm):
    result_html = forms.CharField(
        label="HTML-Quelltext",
        required=False,
        help_text="Aenderungen hier haben Vorrang vor dem visuellen Editor.",
        widget=UnfoldAdminTextareaWidget(attrs={"class": "font-mono", "rows": 18}),
    )

    class Meta:
        model = AIRewriteJob
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["result_html"].initial = self.instance.result_text

    def clean(self):
        cleaned_data = super().clean()
        if "result_html" in self.changed_data:
            cleaned_data["result_text"] = cleaned_data.get("result_html", "")
        return cleaned_data


class AITranslationConfigAdminForm(forms.ModelForm):
    """Render the JSON-backed translation scope as explicit selections."""

    translation_areas = forms.MultipleChoiceField(
        choices=AITranslationConfig.TranslationArea.choices,
        widget=forms.CheckboxSelectMultiple,
        label="Uebersetzungsbereiche",
        help_text="Waehle die Inhalte, die der Uebersetzungsscan verarbeiten soll.",
    )
    record_statuses = forms.MultipleChoiceField(
        choices=AITranslationConfig.RecordStatus.choices,
        widget=forms.CheckboxSelectMultiple,
        label="Datensatzstatus",
        help_text="Datensaetze ohne eigenen Status gelten als aktiv.",
    )

    class Meta:
        model = AITranslationConfig
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["translation_areas"] = sorted(self.instance.selected_translation_areas())
        self.initial["record_statuses"] = sorted(self.instance.selected_record_statuses())


class AITranslationGlossaryEntryAdminForm(forms.ModelForm):
    """Expose the configured target locales as readable select options."""

    target_language = forms.ChoiceField(
        choices=settings.LANGUAGES,
        label="Zielsprache",
        help_text="Waehle die Sprache, in die der Quellbegriff verbindlich uebersetzt wird.",
    )

    class Meta:
        model = AITranslationGlossaryEntry
        fields = "__all__"


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(BaseAdmin):
    list_display = ("name", "model_name", "base_url", "is_active", "created_at")
    search_fields = ("name", "model_name", "base_url")
    list_filter = ("is_active",)


@admin.register(AITranslationConfig)
class AITranslationConfigAdmin(BaseAdmin):
    form = AITranslationConfigAdminForm
    list_display = ("name", "provider", "source_language", "batch_size", "status_retention_days", "is_active", "updated_at")
    search_fields = ("name", "provider__name", "provider__model_name")
    list_filter = ("is_active", "provider")
    actions_detail = ("queue_translation_scan_detail", "archive_expired_translation_states_detail")
    formfield_overrides = {
        **BaseAdmin.formfield_overrides,
        models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"class": "font-mono", "rows": 14})},
    }
    fieldsets = (
        ("Ausfuehrung", {
            "fields": ("name", "provider", "source_language", "batch_size", "status_retention_days", "is_active", "clear_target_on_empty_source"),
            "description": "Es darf nur eine Konfiguration aktiv sein. Der geplante Celery-Task verwendet diese Konfiguration.",
        }),
        ("Uebersetzungsumfang", {
            "fields": ("translation_areas", "record_statuses"),
            "description": "Der Scan verarbeitet nur die ausgewaehlten Bereiche und Datensatzstatus.",
        }),
        ("Uebersetzungsanweisungen", {
            "fields": ("system_prompt", "user_prompt_template", "locale_instructions"),
            "description": "Die Prompt-Vorlagen und Sprachvarianten-Hinweise sind direkt hier editierbar.",
        }),
        ("Zeitstempel", {
            "fields": BaseAdmin.readonly_fields,
            "classes": ("collapse",),
        }),
    )

    @action(description="Uebersetzungsscan jetzt starten", icon="translate")
    def queue_translation_scan_detail(self, request, object_id: str):
        configuration = self.get_object(request, object_id)
        if not configuration:
            self.message_user(request, "Uebersetzungskonfiguration nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ai_aitranslationconfig_changelist"))
        if not configuration.is_active:
            self.message_user(request, "Nur eine aktive Konfiguration kann einen Scan starten.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:ai_aitranslationconfig_change", args=(configuration.pk,)))
        try:
            async_result = queue_ai_translation_scan.delay(configuration.pk)
        except Exception as exc:  # noqa: BLE001 - the user needs the enqueue error in the admin.
            self.message_user(request, f"Uebersetzungsscan konnte nicht eingeplant werden: {exc}", level=messages.ERROR)
        else:
            self.message_user(request, f"Uebersetzungsscan wurde gestartet ({async_result.id}).")
        return HttpResponseRedirect(reverse("admin:ai_aitranslationconfig_change", args=(configuration.pk,)))

    @action(description="Abgelaufene Status aus Liste ausblenden", icon="archive")
    def archive_expired_translation_states_detail(self, request, object_id: str):
        configuration = self.get_object(request, object_id)
        if not configuration:
            self.message_user(request, "Uebersetzungskonfiguration nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ai_aitranslationconfig_changelist"))
        archived_count = AITranslationService().archive_expired_states(configuration=configuration)
        self.message_user(request, f"{archived_count} abgelaufene Status wurden aus der Liste ausgeblendet.")
        return HttpResponseRedirect(reverse("admin:ai_aitranslationconfig_change", args=(configuration.pk,)))


@admin.register(AITranslationGlossaryEntry)
class AITranslationGlossaryEntryAdmin(BaseAdmin):
    form = AITranslationGlossaryEntryAdminForm
    list_display = ("source_term", "target_language", "target_term", "is_active", "updated_at")
    search_fields = ("source_term", "target_term")
    list_filter = ("target_language", "is_active")


@admin.register(AITranslationState)
class AITranslationStateAdmin(BaseAdmin):
    list_display = (
        "target_object", "source_field", "target_language", "configuration", "status",
        "attempt_count", "translated_at", "updated_at",
    )
    search_fields = ("source_field", "target_language", "last_error", "configuration__name")
    list_filter = ("status", "target_language", "configuration", "content_type")
    actions_detail = ("retry_translation_detail",)
    readonly_fields = BaseAdmin.readonly_fields + (
        "configuration", "content_type", "object_id", "source_field", "target_language", "source_hash", "configuration_hash", "status",
        "attempt_count", "celery_task_id", "translated_at", "last_error", "target_object",
    )
    fieldsets = (
        ("Uebersetzung", {
            "fields": ("target_object", "configuration", "source_field", "target_language", "status", "translated_at"),
        }),
        ("Diagnose", {
            "fields": ("content_type", "object_id", "source_hash", "configuration_hash", "attempt_count", "celery_task_id", "last_error", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_archived=False).select_related("configuration", "content_type")

    @admin.display(description="Zielobjekt")
    def target_object(self, obj: AITranslationState):
        model = obj.content_type.model_class()
        target = model._default_manager.filter(pk=obj.object_id).first() if model else None
        return str(target) if target is not None else f"Geloescht ({obj.content_type} #{obj.object_id})"

    @action(description="Erneut einplanen", icon="refresh")
    def retry_translation_detail(self, request, object_id: str):
        state = self.get_object(request, object_id)
        if not state:
            self.message_user(request, "Uebersetzungsstatus nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ai_aitranslationstate_changelist"))
        if state.status == AITranslationState.Status.RUNNING:
            self.message_user(request, "Diese Uebersetzung laeuft bereits.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:ai_aitranslationstate_change", args=(state.pk,)))
        state.status = AITranslationState.Status.PENDING
        state.celery_task_id = ""
        state.last_error = ""
        state.is_archived = False
        state.archived_at = None
        state.save(update_fields=("status", "celery_task_id", "last_error", "is_archived", "archived_at", "updated_at"))
        try:
            async_result = run_ai_translation_state.delay(state.pk)
        except Exception as exc:  # noqa: BLE001 - persist the actionable enqueue failure.
            state.status = AITranslationState.Status.FAILED
            state.last_error = f"Celery enqueue failed: {exc}"
            state.save(update_fields=("status", "last_error", "updated_at"))
            self.message_user(request, f"Uebersetzung konnte nicht eingeplant werden: {exc}", level=messages.ERROR)
        else:
            state.celery_task_id = getattr(async_result, "id", "") or ""
            state.save(update_fields=("celery_task_id", "updated_at"))
            self.message_user(request, "Uebersetzung wurde erneut eingeplant.")
        return HttpResponseRedirect(reverse("admin:ai_aitranslationstate_change", args=(state.pk,)))


@admin.register(AIRewritePrompt)
class AIRewritePromptAdmin(BaseAdmin):
    list_display = ("name", "is_active", "created_at")
    search_fields = ("name", "slug")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AIRewriteJob)
class AIRewriteJobAdmin(BaseAdmin):
    form = AIRewriteJobAdminForm

    class Media:
        js = ("core/admin/ai_rewrite_wysiwyg.js",)

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
        "provider_response", "celery_task_id", "requested_by", "applied_at",
    )
    fieldsets = (
        ("Ergebnis", {
            "fields": ("status", "source_snapshot_preview", "result_text", "result_html", "error_message"),
            "description": "Ergebnis visuell oder als HTML-Quelltext bearbeiten und anschliessend uebernehmen.",
        }),
        ("Kontext", {
            "fields": ("target_object", "field", "prompt", "provider", "rendered_prompt", "provider_response",
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
