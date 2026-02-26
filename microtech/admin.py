from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from core.admin import BaseAdmin
from microtech.models import MicrotechOrderRule, MicrotechSettings


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
    list_display = (
        "priority",
        "name",
        "is_active",
        "customer_type",
        "billing_country_code",
        "shipping_country_code",
        "country_match_mode",
        "zahlungsart_id",
        "versandart_id",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = (
        "name",
        "payment_method_pattern",
        "shipping_method_pattern",
        "billing_country_code",
        "shipping_country_code",
        "payment_position_erp_nr",
        "payment_position_name",
    )
    list_filter = (
        "is_active",
        "customer_type",
        "country_match_mode",
        "na1_mode",
        "add_payment_position",
    )
    ordering = ("priority", "id")

    fieldsets = (
        (
            "Regel",
            {
                "fields": ("name", "is_active", "priority"),
            },
        ),
        (
            "Bedingungen",
            {
                "fields": (
                    "customer_type",
                    "billing_country_code",
                    "shipping_country_code",
                    "country_match_mode",
                    "payment_method_pattern",
                    "shipping_method_pattern",
                ),
                "description": (
                    "Leere Felder gelten als Wildcard. "
                    "payment/shipping pattern pruefen case-insensitive auf 'enthaelt'."
                ),
            },
        ),
        (
            "Ergebnis: Kopf",
            {
                "fields": (
                    "na1_mode",
                    "na1_static_value",
                    "vorgangsart_id",
                    "zahlungsart_id",
                    "versandart_id",
                    "zahlungsbedingung",
                ),
            },
        ),
        (
            "Ergebnis: Zusatzposition Zahlungsart",
            {
                "fields": (
                    "add_payment_position",
                    "payment_position_erp_nr",
                    "payment_position_name",
                    "payment_position_mode",
                    "payment_position_value",
                ),
            },
        ),
    )
