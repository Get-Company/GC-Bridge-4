from django.contrib import admin

from core.admin import BaseAdmin
from .models import ShopwareSettings


@admin.register(ShopwareSettings)
class ShopwareSettingsAdmin(BaseAdmin):
    list_display = ("name", "sales_channel_id", "is_default", "price_factor", "is_active")
    search_fields = ("name", "sales_channel_id")
    list_filter = ("is_default", "is_active")
    fieldsets = (
        ("Allgemein", {"fields": ("name", "sales_channel_id", "is_default", "is_active")}),
        (
            "Preisgestaltung",
            {
                "fields": (
                    "price_factor",
                    "rule_id_price",
                    "currency_id",
                )
            },
        ),
        (
            "Standardwerte",
            {
                "fields": (
                    "tax_high_id",
                    "tax_low_id",
                )
            },
        ),
    )
