from django.contrib import admin
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
                    "Kundentyp wird automatisch erkannt: Firma wenn Name1 wie Firmenname aussieht "
                    "(kein Vorname/Nachname, keine Anrede), sonst Privat. "
                    "Operator und Vergleichswerte sind typabhaengig (String, Integer, Bool, Decimal, Enum). "
                    "Na1 Modus steuert den Empfaengertext in Anschriften: auto/firma_or_salutation/"
                    "salutation_only/static. "
                    "Zusatzposition Zahlungsart anlegen fuegt eine zusaetzliche Vorgangsposition "
                    "mit payment_position_erp_nr hinzu (z. B. P fuer PayPal)."
                ),
            },
        ),
    )
