from django.contrib import admin

from core.admin import BaseAdmin, BaseTabularInline
from .models import Price, Product


class PriceInline(BaseTabularInline):
    model = Price
    fields = (
        "price",
        "rebate_quantity",
        "rebate_price",
        "special_price",
        "special_start_date",
        "special_end_date",
        "created_at",
        "updated_at",
    )


@admin.register(Product)
class ProductAdmin(BaseAdmin):
    list_display = ("sku", "name", "is_active", "created_at")
    search_fields = ("sku", "name")
    list_filter = ("is_active",)
    inlines = (PriceInline,)


@admin.register(Price)
class PriceAdmin(BaseAdmin):
    list_display = ("product", "price", "special_price", "rebate_price", "created_at")
    search_fields = ("product__erp_nr", "product__name")
    list_filter = ("created_at",)
