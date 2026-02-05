from django.contrib import admin

from core.admin import BaseAdmin
from .models import ShopwareSettings


@admin.register(ShopwareSettings)
class ShopwareSettingsAdmin(BaseAdmin):
    list_display = ("name", "sales_channel_id", "is_active")
    search_fields = ("name", "sales_channel_id")
    list_filter = ("is_active",)
    fieldsets = (
        ("General", {"fields": ("name", "sales_channel_id", "is_active")}),
        (
            "Defaults",
            {
                "fields": (
                    "tax_high_id",
                    "tax_low_id",
                    "currency_id",
                    "rule_id_price",
                )
            },
        ),
    )
