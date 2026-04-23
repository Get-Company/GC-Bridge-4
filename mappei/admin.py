from django import forms
from django.contrib import admin
from django.contrib.admin.views.autocomplete import AutocompleteJsonView
from django.contrib.admin.widgets import AutocompleteSelect
from django.db.models import Prefetch
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.admin import BaseAdmin, BaseTabularInline
from products.models import Product, ProductImage

from .models import MappeiProduct, MappeiPriceSnapshot, MappeiProductMapping


class MappeiProductMappingAutocompleteSelect(AutocompleteSelect):
    url_name = "%s:mappei_mappeiproductmapping_visual_autocomplete"

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs=extra_attrs)
        classes = attrs.get("class", "").split()
        attrs["class"] = " ".join(
            [class_name for class_name in classes if class_name != "admin-autocomplete"]
        )
        return attrs

    @property
    def media(self):
        return super().media + forms.Media(
            js=("mappei/admin/product_mapping_autocomplete.js",),
            css={
                "all": ("mappei/admin/product_mapping_autocomplete.css",),
            },
        )


class MappeiProductMappingAutocompleteJsonView(AutocompleteJsonView):
    def serialize_result(self, obj, to_field_name):
        result = super().serialize_result(obj, to_field_name)
        image_url = self._get_image_url(obj)
        if image_url:
            result["image_url"] = image_url
        return result

    @staticmethod
    def _get_image_url(obj) -> str:
        if isinstance(obj, MappeiProduct):
            return obj.image_url or ""
        if isinstance(obj, Product):
            image = obj.first_image
            return image.url if image else ""
        return ""


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
    list_display = (
        "mappei_product_image_display",
        "mappei_product",
        "product_image_display",
        "product",
    )
    search_fields = ("mappei_product__artikelnr", "mappei_product__name", "product__erp_nr", "product__name")
    autocomplete_fields = ("mappei_product", "product")

    @admin.display(description=_("Mappei Bild"))
    def mappei_product_image_display(self, obj):
        image_url = obj.mappei_product.image_url if obj.mappei_product_id else ""
        return self._thumbnail_html(image_url)

    @admin.display(description=_("Produktbild"))
    def product_image_display(self, obj):
        image = obj.product.first_image if obj.product_id else None
        return self._thumbnail_html(image.url if image else "")

    @staticmethod
    def _thumbnail_html(image_url: str):
        if not image_url:
            return "–"
        return format_html(
            '<img src="{}" loading="lazy" style="width:52px;height:52px;object-fit:contain;border-radius:4px;" />',
            image_url,
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("mappei_product", "product").prefetch_related(
            Prefetch(
                "product__product_images",
                queryset=ProductImage.objects.select_related("image").order_by("order", "id"),
                to_attr="ordered_product_images",
            )
        )

    def get_custom_urls(self):
        urls = super().get_custom_urls()
        return (
            *urls,
            (
                "visual-autocomplete/",
                "mappei_mappeiproductmapping_visual_autocomplete",
                self.visual_autocomplete_view,
            ),
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in self.autocomplete_fields:
            kwargs["widget"] = MappeiProductMappingAutocompleteSelect(
                db_field,
                self.admin_site,
                attrs={"class": "mappei-product-mapping-autocomplete"},
                using=kwargs.get("using"),
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def visual_autocomplete_view(self, request, **kwargs):
        return MappeiProductMappingAutocompleteJsonView.as_view(
            admin_site=self.admin_site,
        )(request)
