from django.contrib import admin

from core.admin import BaseAdmin
from .models import Product


@admin.register(Product)
class ProductAdmin(BaseAdmin):
    list_display = ("sku", "name", "is_active", "created_at")
    search_fields = ("sku", "name")
    list_filter = ("is_active",)
