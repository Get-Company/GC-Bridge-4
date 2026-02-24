from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.http import HttpResponseRedirect
from django.urls import reverse
from modeltranslation.admin import TabbedTranslationAdmin

from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseStackedInline, BaseTabularInline
from core.admin_utils import log_admin_change
from shopware.services import ProductService
from .models import Category, Price, Product, Storage, Tax


class StorageInline(BaseStackedInline):
    model = Storage
    fields = ("stock", "virtual_stock", "location")
    extra = 0


class PriceInline(BaseStackedInline):
    model = Price
    fields = (
        "sales_channel",
        "price",
        "rebate_quantity",
        "rebate_price",
        "special_percentage",
        "special_price",
        "special_start_date",
        "special_end_date",
        "created_at",
        "updated_at",
    )


@admin.register(Product)
class ProductAdmin(TabbedTranslationAdmin, BaseAdmin):
    formfield_overrides = {
        **getattr(TabbedTranslationAdmin, "formfield_overrides", {}),
        **BaseAdmin.formfield_overrides,
    }
    compressed_fields = BaseAdmin.compressed_fields
    warn_unsaved_form = BaseAdmin.warn_unsaved_form
    change_form_show_cancel_button = BaseAdmin.change_form_show_cancel_button
    list_filter_sheet = BaseAdmin.list_filter_sheet
    list_horizontal_scrollbar_top = BaseAdmin.list_horizontal_scrollbar_top
    list_display = ("erp_nr", "name", "is_active", "created_at")
    search_fields = ("erp_nr", "sku", "name")
    list_filter = [
        ("is_active", BooleanRadioFilter),
        ("tax", RelatedDropdownFilter),
        ("categories", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    inlines = (StorageInline, PriceInline)
    filter_horizontal = ("categories",)
    actions = ("sync_from_microtech", "sync_to_shopware")
    actions_detail = ("sync_from_microtech_detail", "sync_to_shopware_detail")

    def _redirect_to_change_page(self, object_id: str) -> HttpResponseRedirect:
        change_url = reverse("admin:products_product_change", args=(object_id,))
        return HttpResponseRedirect(change_url)

    def _log_admin_error(self, request, message: str, *, obj: Product | None = None) -> None:
        log_admin_change(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(Product).id,
            object_id=str(obj.pk) if obj else None,
            object_repr=str(obj) if obj else "Shopware Sync",
            message=message,
        )

    def _sync_products_bulk(self, products, service: ProductService, request=None) -> tuple[int, int, list[str]]:
        success_count = 0
        error_count = 0
        error_messages: list[str] = []
        batch_size = 50
        products = list(products)

        for offset in range(0, len(products), batch_size):
            batch = products[offset : offset + batch_size]
            missing = [p.erp_nr for p in batch if not p.sku]
            sku_map = service.get_sku_map(missing) if missing else {}

            payloads = []
            payload_products: list[Product] = []
            fallback_products: list[Product] = []
            for product in batch:
                effective_sku = product.sku
                if not effective_sku:
                    resolved_sku = sku_map.get(product.erp_nr)
                    if resolved_sku:
                        effective_sku = resolved_sku
                        product.sku = resolved_sku
                        product.save(update_fields=["sku"])

                payload = {
                    "productNumber": product.erp_nr,
                    "active": product.is_active,
                }
                if effective_sku:
                    payload["id"] = effective_sku
                else:
                    fallback_products.append(product)
                if product.name:
                    payload["name"] = product.name
                if product.description is not None:
                    payload["description"] = product.description

                try:
                    storage = product.storage
                except Storage.DoesNotExist:
                    storage = None
                if storage:
                    payload["stock"] = storage.get_stock

                payloads.append(payload)
                payload_products.append(product)

            if not payloads:
                continue

            try:
                service.bulk_upsert(payloads)
                success_count += len(payload_products)

                if fallback_products:
                    refreshed_map = service.get_sku_map([product.erp_nr for product in fallback_products])
                    for product in fallback_products:
                        resolved_sku = refreshed_map.get(product.erp_nr)
                        if resolved_sku:
                            product.sku = resolved_sku
                            product.save(update_fields=["sku"])
                            continue
                        error_count += 1
                        msg = f"SKU konnte nach Fallback-Upsert nicht aufgeloest werden fuer Artikelnr. {product.erp_nr}"
                        error_messages.append(msg)
                        if request:
                            self._log_admin_error(request, msg, obj=product)
            except Exception as exc:
                error_count += len(payload_products)
                msg = str(exc)
                error_messages.append(msg)
                if request:
                    for product in payload_products:
                        self._log_admin_error(
                            request,
                            f"Shopware bulk sync fehlgeschlagen fuer {product.erp_nr}: {exc}",
                            obj=product,
                        )

        return success_count, error_count, error_messages

    @action(
        description="Von Microtech synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_microtech(self, request, queryset):
        erp_nrs = list(queryset.values_list("erp_nr", flat=True))
        if not erp_nrs:
            self.message_user(request, "Keine Produkte ausgewaehlt.", level=messages.WARNING)
            return
        try:
            call_command("microtech_sync_products", *erp_nrs)
            self.message_user(request, f"{len(erp_nrs)} Produkt(e) aus Microtech synchronisiert.")
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Microtech sync failed: {exc}",
            )
            self.message_user(request, f"Microtech Sync fehlgeschlagen: {exc}", level=messages.ERROR)

    @action(
        description="Von Microtech synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_microtech_detail(self, request, object_id: str):
        product = self.get_object(request, object_id)
        if not product:
            self.message_user(request, "Produkt nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)
        try:
            call_command("microtech_sync_products", product.erp_nr)
            self.message_user(request, f"Produkt {product.erp_nr} aus Microtech synchronisiert.")
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Microtech sync failed for {product.erp_nr}: {exc}",
                obj=product,
            )
            self.message_user(request, f"Microtech Sync fehlgeschlagen: {exc}", level=messages.ERROR)
        return self._redirect_to_change_page(object_id)

    @action(
        description="Nach Shopware synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_shopware(self, request, queryset):
        service = ProductService()
        success_count, error_count, error_messages = self._sync_products_bulk(queryset, service, request=request)
        if success_count:
            self.message_user(request, f"{success_count} Produkt(e) synchronisiert.")
        if error_count:
            detail = f": {error_messages[0]}" if error_messages else ""
            self.message_user(
                request,
                f"{error_count} Produkt(e) mit Fehlern{detail} — Details im Produkt-Verlauf (History).",
                level=messages.ERROR,
            )

    @action(
        description="Nach Shopware synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_shopware_detail(self, request, object_id: str):
        product = self.get_object(request, object_id)
        if not product:
            self.message_user(request, "Produkt nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)
        try:
            success_count, error_count, error_messages = self._sync_products_bulk([product], ProductService(), request=request)
            if success_count:
                self.message_user(request, f"Produkt {product.erp_nr} synchronisiert.")
            if error_count:
                detail = error_messages[0] if error_messages else "Unbekannter Fehler"
                self.message_user(
                    request,
                    f"Sync fehlgeschlagen: {detail} — Details im Produkt-Verlauf (History).",
                    level=messages.ERROR,
                )
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Shopware sync fehlgeschlagen fuer {product.erp_nr}: {exc}",
                obj=product,
            )
            self.message_user(
                request,
                f"Sync fehlgeschlagen: {exc} — Details im Produkt-Verlauf (History).",
                level=messages.ERROR,
            )
        return self._redirect_to_change_page(object_id)


@admin.register(Price)
class PriceAdmin(BaseAdmin):
    list_display = ("product", "sales_channel", "price", "special_percentage", "special_price", "special_active", "rebate_price", "created_at")
    search_fields = ("product__erp_nr", "product__name", "sales_channel__name")
    list_filter = [
        ("sales_channel", RelatedDropdownFilter),
        ("price", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]

    @admin.display(boolean=True, description="Sonderpreis aktiv")
    def special_active(self, obj: Price) -> bool:
        return obj.is_special_active


@admin.register(Storage)
class StorageAdmin(BaseAdmin):
    list_display = ("product", "stock", "virtual_stock", "location", "created_at")
    search_fields = ("product__erp_nr", "product__name", "location")
    list_filter = [
        ("stock", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]


@admin.register(Category)
class CategoryAdmin(BaseAdmin):
    list_display = ("name", "slug", "parent", "created_at")
    search_fields = ("name", "slug", "parent__name")
    list_filter = [
        ("parent", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]


@admin.register(Tax)
class TaxAdmin(BaseAdmin):
    list_display = ("name", "rate", "created_at")
    search_fields = ("name",)
    list_filter = [
        ("rate", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]
