from django.contrib import admin
from django.db import models
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.html import format_html
from django.urls import reverse

from core.admin import BaseAdmin, BaseStackedInline
from microtech.forms import (
    MicrotechOrderRuleActionForm,
    MicrotechOrderRuleConditionForm,
    condition_example_for_field,
)
from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleDjangoFieldPolicy,
    MicrotechOrderRuleOperator,
    MicrotechSettings,
    MicrotechSwissCustomsFieldMapping,
)
from microtech.rule_builder import (
    get_allowed_operator_codes,
    get_dataset_defs,
    get_dataset_field_defs,
    get_django_field_defs,
    get_rule_action_target_defs,
)
from microtech.views.autocomplete import (
    MicrotechDatasetFieldAutocompleteView,
    MicrotechOrderRuleOperatorAutocompleteView,
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
                "description": "Benutzer fuer automatische und manuelle Sync-Vorgaenge.",
            },
        ),
        (
            "Vorgang-Standardwerte",
            {
                "fields": ("default_vorgangsart_id", "default_zahlungsart_id", "default_versandart_id"),
                "description": "Standard-IDs fuer neue Microtech-Bestellungen (Vorgaenge).",
            },
        ),
    )


@admin.register(MicrotechSwissCustomsFieldMapping)
class MicrotechSwissCustomsFieldMappingAdmin(BaseAdmin):
    list_display = (
        "priority",
        "portal_field",
        "section",
        "source_type",
        "source_preview_short",
        "is_required",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("portal_field", "source_path", "static_value", "help_text")
    list_filter = ("is_active", "section", "source_type", "is_required", "value_kind")
    ordering = ("priority", "portal_field", "id")
    fieldsets = (
        (
            "Zollportal Feldmapping",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "portal_field",
                    "section",
                    "source_type",
                    "source_path",
                    "static_value",
                    "value_kind",
                    "is_required",
                    "help_text",
                ),
                "description": (
                    "Mapping der GLS-/Schweiz-Zollfelder auf statische Werte oder Quellen aus dem neuen Django-Projekt. "
                    "Bei 'computed' steht im Quellpfad ein Resolver-Key fuer spaetere Aufloesung."
                ),
            },
        ),
    )

    @admin.display(description="Quelle / Wert")
    def source_preview_short(self, obj):
        value = (obj.source_preview or "").strip()
        if len(value) > 80:
            return f"{value[:77]}..."
        return value


@admin.register(MicrotechOrderRule)
class MicrotechOrderRuleAdmin(BaseAdmin):
    class ConditionInline(BaseStackedInline):
        model = MicrotechOrderRuleCondition
        form = MicrotechOrderRuleConditionForm
        fields = (
            "is_active",
            "priority",
            "django_field",
            "operator",
            "expected_value",
            "value_example",
        )
        autocomplete_fields = ("django_field", "operator")
        readonly_fields = BaseStackedInline.readonly_fields + ("value_example",)
        extra = 0
        verbose_name = "Bedingung"
        verbose_name_plural = "Wann greift die Regel?"

        @admin.display(description="Beispiel")
        def value_example(self, obj):
            if not obj:
                return "Waehle zuerst ein Feld. Der Beispielwert folgt automatisch."
            return condition_example_for_field(obj.django_field_path)

    class ActionInline(BaseStackedInline):
        model = MicrotechOrderRuleAction
        form = MicrotechOrderRuleActionForm
        fields = (
            "is_active",
            "priority",
            "ui_action",
            "dataset_field",
            "target_value",
            "action_context_preview",
        )
        autocomplete_fields = ("dataset_field",)
        readonly_fields = BaseStackedInline.readonly_fields + ("action_context_preview",)
        extra = 0
        verbose_name = "Aktion"
        verbose_name_plural = "Was soll in Microtech passieren?"

        @admin.display(description="Zielkontext")
        def action_context_preview(self, obj):
            if not obj:
                return "Waehle zuerst eine fachliche Aktion."
            if obj.action_type == MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION:
                return "Legt eine Zusatzposition an. Zielwert = ERP-Nr der Position."
            if obj.dataset_field_id and obj.dataset_id:
                return obj.dataset_field.display_label
            return "Waehle ein passendes Microtech-Zielfeld."

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
    readonly_fields = BaseAdmin.readonly_fields + ("live_rule_summary",)

    class Media:
        js = ("microtech/js/order_rule_builder.js",)
        css = {
            "all": ("microtech/css/order_rule_builder.css",),
        }

    def get_custom_urls(self):
        urls = super().get_custom_urls()
        return (
            *urls,
            (
                "rule-builder-meta/",
                "microtech_orderrule_builder_meta",
                self.rule_builder_meta_view,
            ),
            (
                "operator-autocomplete/",
                "microtech_orderrule_operator_autocomplete",
                MicrotechOrderRuleOperatorAutocompleteView.as_view(),
            ),
            (
                "dataset-field-autocomplete/",
                "microtech_orderrule_dataset_field_autocomplete",
                MicrotechDatasetFieldAutocompleteView.as_view(),
            ),
        )

    def rule_builder_meta_view(self, request, **kwargs):
        if not self.has_view_permission(request):
            return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)
        payload = {
            "ok": True,
            "operators": [
                {
                    "id": item.id,
                    "code": item.code,
                    "name": item.name,
                    "engine_operator": item.engine_operator,
                    "hint": item.hint,
                }
                for item in MicrotechOrderRuleOperator.objects.filter(is_active=True).order_by("priority", "id")
            ],
            "django_fields": [
                {
                    "id": item.catalog_id,
                    "path": item.path,
                    "label": item.label,
                    "value_kind": item.value_kind,
                    "hint": item.hint,
                    "example": item.example,
                    "input_type": item.input_type,
                    "accepts_date_only": item.accepts_date_only,
                    "allowed_operator_codes": sorted(
                        get_allowed_operator_codes(field_path=item.path, django_field_id=item.catalog_id)
                    ),
                }
                for item in get_django_field_defs()
            ],
            "action_targets": [
                {
                    "code": item.code,
                    "label": item.label,
                    "action_type": item.action_type,
                    "dataset_source_identifiers": list(item.dataset_source_identifiers),
                    "dataset_names": list(item.dataset_names),
                    "target_value_label": item.target_value_label,
                    "target_value_help": item.target_value_help,
                }
                for item in get_rule_action_target_defs()
            ],
            "datasets": [
                {
                    "id": item.id,
                    "code": item.code,
                    "name": item.name,
                    "description": item.description,
                    "source_identifier": item.source_identifier,
                }
                for item in get_dataset_defs()
            ],
            "dataset_fields": [
                {
                    "id": item.id,
                    "dataset_id": item.dataset_id,
                    "field_name": item.field_name,
                    "label": item.label,
                    "field_type": item.field_type,
                    "can_access": item.can_access,
                    "is_calc_field": item.is_calc_field,
                }
                for item in get_dataset_field_defs()
            ],
        }
        return JsonResponse(payload)

    @admin.display(description="Live-Zusammenfassung")
    def live_rule_summary(self, obj):
        return format_html(
            """
            <section class="rulebuilder-summary-card" id="rulebuilder-live-summary" aria-live="polite">
              <h3 class="rulebuilder-summary-title">Regel-Zusammenfassung</h3>
              <p class="rulebuilder-summary-text">
                Noch keine vollstaendige Regel. Waehle Bedingungen und Aktionen, dann erscheint hier die Klartext-Zusammenfassung.
              </p>
              <ul class="rulebuilder-summary-warnings" id="rulebuilder-summary-warnings"></ul>
            </section>
            """
        )

    fieldsets = (
        (
            "Grundregel",
            {
                "fields": ("name", "is_active", "priority", "condition_logic"),
                "description": (
                    "Prioritaet steuert die Reihenfolge. Die erste passende aktive Regel gewinnt."
                ),
            },
        ),
        (
            "Wann greift die Regel?",
            {
                "fields": (),
                "description": (
                    "Definiere die Ausloeser in Fachsprache. "
                    "Ohne aktive Bedingungen gilt die Regel als globaler Fallback."
                ),
            },
        ),
        (
            "Was soll in Microtech passieren?",
            {
                "fields": (),
                "description": (
                    "Waehle fachliche Aktionen. Das technische Ziel-Dataset wird im Hintergrund gefuehrt."
                ),
            },
        ),
        (
            "Klartext-Vorschau",
            {
                "fields": ("live_rule_summary",),
                "description": "Die Vorschau aktualisiert sich waehrend der Bearbeitung.",
            },
        ),
    )


@admin.register(MicrotechOrderRuleDjangoField)
class MicrotechOrderRuleDjangoFieldAdmin(BaseAdmin):
    list_display = ("priority", "label", "field_path", "value_kind", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("field_path", "label", "hint", "example")
    list_filter = ("is_active", "value_kind")
    ordering = ("priority", "field_path", "id")
    fieldsets = (
        (
            "Django Feldkatalog",
            {
                "fields": ("is_active", "priority", "field_path", "label", "value_kind", "hint", "example"),
            },
        ),
    )


@admin.register(MicrotechOrderRuleOperator)
class MicrotechOrderRuleOperatorAdmin(BaseAdmin):
    list_display = ("priority", "name", "code", "engine_operator", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("code", "name", "hint")
    list_filter = ("is_active", "engine_operator")
    ordering = ("priority", "id")
    fieldsets = (
        (
            "Operator",
            {
                "fields": ("is_active", "priority", "code", "name", "engine_operator", "hint"),
            },
        ),
    )



@admin.register(MicrotechOrderRuleDjangoFieldPolicy)
class MicrotechOrderRuleDjangoFieldPolicyAdmin(BaseAdmin):
    list_display = ("priority", "field_path", "label_override", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("field_path", "label_override", "hint")
    list_filter = ("is_active",)
    ordering = ("priority", "field_path", "id")
    filter_horizontal = ("allowed_operators",)
    fieldsets = (
        (
            "Django Bedingungsfeld Policy",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "field_path",
                    "label_override",
                    "hint",
                    "allowed_operators",
                ),
            },
        ),
    )


@admin.register(MicrotechDatasetCatalog)
class MicrotechDatasetCatalogAdmin(BaseAdmin):
    list_display = ("priority", "name", "description", "code", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("code", "name", "description", "source_identifier")
    list_filter = ("is_active",)
    ordering = ("priority", "name", "id")
    fieldsets = (
        (
            "Dataset",
            {
                "fields": ("is_active", "priority", "code", "name", "description", "source_identifier"),
            },
        ),
    )


@admin.register(MicrotechDatasetField)
class MicrotechDatasetFieldAdmin(BaseAdmin):
    list_display = (
        "priority",
        "dataset",
        "field_name",
        "field_type",
        "is_calc_field",
        "can_access",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("field_name", "label", "field_type", "dataset__name", "dataset__description")
    list_filter = ("is_active", "is_calc_field", "can_access", "field_type", "dataset")

    def get_search_results(self, request, queryset, search_term):
        # Support "Dataset.Field" search (e.g. "Vorgang.Such")
        if "." in search_term:
            parts = search_term.split(".", 1)
            dataset_term = parts[0].strip()
            field_term = parts[1].strip()
            qs = queryset.filter(dataset__name__icontains=dataset_term)
            if field_term:
                qs = qs.filter(
                    models.Q(field_name__icontains=field_term)
                    | models.Q(label__icontains=field_term)
                )
            return qs, False
        return super().get_search_results(request, queryset, search_term)
    ordering = ("dataset__priority", "dataset__name", "priority", "field_name", "id")
    autocomplete_fields = ("dataset",)
    fieldsets = (
        (
            "Dataset Feld",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "dataset",
                    "field_name",
                    "label",
                    "field_type",
                    "is_calc_field",
                    "can_access",
                ),
            },
        ),
    )
