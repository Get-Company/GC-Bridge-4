from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.admin import BaseAdmin, BaseTabularInline

from .models import MappeiProduct, MappeiPriceSnapshot, MappeiProductMapping


class MappeiPriceSnapshotInline(BaseTabularInline):
    model = MappeiPriceSnapshot
    extra = 0
    max_num = 0  # read-only: no adding via inline
    can_delete = False
    fields = (
        "scraped_at",
        "preis",
        "staffelpreis_min",
        "staffelpreis_max",
        "staffelpreismenge_min",
        "staffelpreismenge_max",
        "partial_success",
    )
    readonly_fields = fields
    ordering = ("-scraped_at",)
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MappeiProduct)
class MappeiProductAdmin(BaseAdmin):
    list_display = (
        "product_image_display",
        "artikelnr",
        "name",
        "hat_staffel",
        "current_price_display",
        "last_scraped_at",
        "has_mapping",
    )
    list_filter = ("hat_staffel",)
    search_fields = ("artikelnr", "name")
    readonly_fields = ("last_scraped_at", "artikelnr", "url_link", "product_image_display")
    fields = ("artikelnr", "name", "url_link", "product_image_display", "vpe_menge", "vpe_einheit", "hat_staffel", "last_scraped_at")
    inlines = [MappeiPriceSnapshotInline]

    @admin.display(description="")
    def product_image_display(self, obj):
        if obj.image_url:
            return format_html(
                '<img src="{}" loading="lazy" style="height:48px;width:auto;object-fit:contain;" />',
                obj.image_url,
            )
        return "–"

    @admin.display(description=_("Aktueller Preis"))
    def current_price_display(self, obj):
        snapshot = obj.get_latest_snapshot()
        if snapshot:
            return f"{snapshot.preis} €"
        return "–"

    @admin.display(description=_("Mapping"), boolean=True)
    def has_mapping(self, obj):
        return hasattr(obj, "mapping")

    @admin.display(description=_("URL"))
    def url_link(self, obj):
        if obj.url:
            return format_html('<a href="{}" target="_blank">{}</a>', obj.url, obj.url)
        return "–"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("price_snapshots").select_related()


@admin.register(MappeiPriceSnapshot)
class MappeiPriceSnapshotAdmin(BaseAdmin):
    list_display = (
        "product",
        "scraped_at",
        "preis",
        "staffelpreis_min",
        "staffelpreis_max",
        "staffelpreismenge_min",
        "staffelpreismenge_max",
        "partial_success",
    )
    list_filter = ("partial_success",)
    search_fields = ("product__artikelnr",)
    readonly_fields = (
        "product",
        "scraped_at",
        "preis",
        "staffelpreis_min",
        "staffelpreis_max",
        "staffelpreismenge_min",
        "staffelpreismenge_max",
        "partial_success",
    )
    ordering = ("-scraped_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MappeiProductMapping)
class MappeiProductMappingAdmin(BaseAdmin):
    list_display = ("mappei_product", "product")
    search_fields = ("mappei_product__artikelnr", "mappei_product__name", "product__erp_nr", "product__name")
    autocomplete_fields = ("mappei_product", "product")
