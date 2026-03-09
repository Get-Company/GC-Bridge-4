from django.contrib import admin
from django.http import JsonResponse
from django.http import HttpResponseRedirect
from django.urls import reverse

from core.admin import BaseAdmin, BaseTabularInline
from microtech.forms import (
    MicrotechOrderRuleActionForm,
    MicrotechOrderRuleConditionForm,
    action_example_for_field,
    condition_example_for_field,
)
from microtech.models import (
    MicrotechOrderRuleActionTarget,
    MicrotechOrderRuleConditionSource,
    MicrotechOrderRuleOperator,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCondition,
    MicrotechSettings,
)
from microtech.rule_builder import get_action_target_defs, get_condition_source_defs, get_operator_defs


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
        form = MicrotechOrderRuleConditionForm
        fields = (
            "is_active",
            "priority",
            "source_field",
            "operator",
            "expected_value",
            "value_example",
        )
        readonly_fields = BaseTabularInline.readonly_fields + ("value_example",)
        extra = 0

        @admin.display(description="Beispiel")
        def value_example(self, obj):
            if not obj:
                return "-"
            return condition_example_for_field(obj.source_field)

    class ActionInline(BaseTabularInline):
        model = MicrotechOrderRuleAction
        form = MicrotechOrderRuleActionForm
        fields = (
            "is_active",
            "priority",
            "target_field",
            "target_value",
            "value_example",
        )
        readonly_fields = BaseTabularInline.readonly_fields + ("value_example",)
        extra = 0

        @admin.display(description="Beispiel")
        def value_example(self, obj):
            if not obj:
                return "-"
            return action_example_for_field(obj.target_field)

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
            "condition_sources": [
                {
                    "code": item.code,
                    "name": item.name,
                    "engine_source_field": item.engine_source_field,
                    "value_type": item.value_type,
                    "allowed_operator_codes": list(item.allowed_operator_codes),
                    "hint": item.hint,
                    "example": item.example,
                }
                for item in get_condition_source_defs()
            ],
            "action_targets": [
                {
                    "code": item.code,
                    "name": item.name,
                    "engine_target_field": item.engine_target_field,
                    "value_type": item.value_type,
                    "enum_values": list(item.enum_values),
                    "hint": item.hint,
                    "example": item.example,
                }
                for item in get_action_target_defs()
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
            "Hinweise fuer Regelbuilder",
            {
                "fields": (),
                "description": (
                    "Source/Target-Felder und Operatoren werden in separaten Rulebuilder-Tabellen gepflegt. "
                    "Operatoren werden im Inline je Source-Feld gefiltert."
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


@admin.register(MicrotechOrderRuleConditionSource)
class MicrotechOrderRuleConditionSourceAdmin(BaseAdmin):
    list_display = (
        "priority",
        "name",
        "code",
        "engine_source_field",
        "value_type",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("code", "name", "hint", "example")
    list_filter = ("is_active", "value_type", "engine_source_field")
    ordering = ("priority", "id")
    filter_horizontal = ("operators",)
    fieldsets = (
        (
            "Condition Source Feld",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "code",
                    "name",
                    "engine_source_field",
                    "value_type",
                    "operators",
                    "hint",
                    "example",
                ),
            },
        ),
    )


@admin.register(MicrotechOrderRuleActionTarget)
class MicrotechOrderRuleActionTargetAdmin(BaseAdmin):
    list_display = (
        "priority",
        "name",
        "code",
        "engine_target_field",
        "value_type",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("code", "name", "hint", "example")
    list_filter = ("is_active", "value_type", "engine_target_field")
    ordering = ("priority", "id")
    fieldsets = (
        (
            "Action Target Feld",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "code",
                    "name",
                    "engine_target_field",
                    "value_type",
                    "enum_values",
                    "hint",
                    "example",
                ),
            },
        ),
    )
