from django.contrib import admin
from django.forms import PasswordInput
from django.http import HttpResponseRedirect
from django.urls import reverse

from core.admin import BaseAdmin
from .models import ShopwareConnection, ShopwareSettings


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


@admin.register(ShopwareConnection)
class ShopwareConnectionAdmin(SingletonAdmin):
    fieldsets = (
        (
            "API-Verbindung",
            {
                "fields": ("api_url", "grant_type"),
            },
        ),
        (
            "Zugangsdaten",
            {
                "fields": ("client_id", "client_secret", "username", "password"),
            },
        ),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ("client_secret", "password"):
            kwargs["widget"] = PasswordInput(render_value=True)
        return super().formfield_for_dbfield(db_field, request, **kwargs)


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
