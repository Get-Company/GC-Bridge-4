from django.contrib import admin
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse

from core.admin import BaseAdmin, BaseTabularInline
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
    MicrotechOrderRuleDjangoFieldPolicy,
    MicrotechOrderRuleOperator,
    MicrotechSettings,
)
from microtech.rule_builder import (
    get_dataset_defs,
    get_dataset_field_defs,
    get_django_field_defs,
    get_operator_defs,
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


@admin.register(MicrotechOrderRule)
class MicrotechOrderRuleAdmin(BaseAdmin):
    class ConditionInline(BaseTabularInline):
        model = MicrotechOrderRuleCondition
        form = MicrotechOrderRuleConditionForm
        fields = (
            "is_active",
            "priority",
            "django_field_path",
            "operator_code",
            "expected_value",
            "value_example",
        )
        readonly_fields = BaseTabularInline.readonly_fields + ("value_example",)
        extra = 0

        @admin.display(description="Beispiel")
        def value_example(self, obj):
            if not obj:
                return "-"
            return condition_example_for_field(obj.django_field_path)

    class ActionInline(BaseTabularInline):
        model = MicrotechOrderRuleAction
        form = MicrotechOrderRuleActionForm
        fields = (
            "is_active",
            "priority",
            "action_type",
            "dataset",
            "dataset_field",
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

    class Media:
        js = ("microtech/js/order_rule_builder.js",)

    def get_custom_urls(self):
        urls = super().get_custom_urls()
        return (
            *urls,
            (
                "rule-builder-meta/",
                "microtech_orderrule_builder_meta",
                self.rule_builder_meta_view,
            ),
        )

    def rule_builder_meta_view(self, request, **kwargs):
        if not self.has_view_permission(request):
            return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)
        payload = {
            "ok": True,
            "operators": [
                {
                    "code": item.code,
                    "name": item.name,
                    "engine_operator": item.engine_operator,
                    "hint": item.hint,
                }
                for item in get_operator_defs()
            ],
            "django_fields": [
                {
                    "path": item.path,
                    "label": item.label,
                    "value_kind": item.value_kind,
                    "allowed_operator_codes": list(item.allowed_operator_codes),
                    "hint": item.hint,
                    "example": item.example,
                }
                for item in get_django_field_defs()
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
        (
            "Hinweise fuer Rulebuilder",
            {
                "fields": (),
                "description": (
                    "Bedingungsfelder werden ueber Django-Feldpfade (Autocomplete) gewaehlt. "
                    "Operatoren werden feldtypbasiert gefiltert und optional ueber Feld-Policies eingeschraenkt. "
                    "Aktionen waehlen Dataset und Dataset-Feld."
                ),
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
    list_display = (
        "priority",
        "field_path",
        "label_override",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("field_path", "label_override", "hint")
    list_filter = ("is_active",)
    ordering = ("priority", "id")
    filter_horizontal = ("allowed_operators",)
    fieldsets = (
        (
            "Django Bedingungsfeld",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "field_path",
                    "label_override",
                    "allowed_operators",
                    "hint",
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
