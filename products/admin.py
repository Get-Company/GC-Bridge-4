from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.http import HttpResponseRedirect
from django.urls import reverse
from modeltranslation.admin import TabbedTranslationAdmin

from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from core.admin_utils import log_admin_change
from shopware.services import ProductService
from .models import Price, Product, Storage


class PriceInline(BaseTabularInline):
    model = Price
    fields = (
        "sales_channel",
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
class ProductAdmin(TabbedTranslationAdmin, BaseAdmin):
    list_display = ("sku", "name", "is_active", "created_at")
    search_fields = ("sku", "name")
    list_filter = ("is_active",)
    inlines = (PriceInline,)
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

    def _sync_products_bulk(self, products, service: ProductService, request=None) -> tuple[int, int]:
        success_count = 0
        error_count = 0
        batch_size = 50
        products = list(products)

        for offset in range(0, len(products), batch_size):
            batch = products[offset : offset + batch_size]
            missing = [p.erp_nr for p in batch if not p.sku]
            if missing:
                sku_map = service.get_sku_map(missing)
                for product in batch:
                    if product.sku or product.erp_nr not in sku_map:
                        continue
                    product.sku = sku_map[product.erp_nr]
                    product.save(update_fields=["sku"])

                for product in batch:
                    if product.sku:
                        continue
                    error_count += 1
                    if request:
                        self._log_admin_error(
                            request,
                            f"Shopware SKU not found for productNumber {product.erp_nr}.",
                            obj=product,
                        )

            payloads = []
            for product in batch:
                if not product.sku:
                    continue
                payload = {
                    "id": product.sku,
                    "productNumber": product.erp_nr,
                    "active": product.is_active,
                }
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

            if not payloads:
                continue

            try:
                service.bulk_upsert(payloads)
                success_count += len(payloads)
            except Exception as exc:
                error_count += len(payloads)
                if request:
                    for product in batch:
                        self._log_admin_error(
                            request,
                            f"Shopware bulk sync failed for {product.erp_nr}: {exc}",
                            obj=product,
                        )

        return success_count, error_count

    @action(
        description="Sync from Microtech",
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
        description="Sync from Microtech",
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
        description="Sync to Shopware6",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_shopware(self, request, queryset):
        service = ProductService()
        success_count, error_count = self._sync_products_bulk(queryset, service, request=request)
        if success_count:
            self.message_user(request, f"{success_count} Produkt(e) synchronisiert.")
        if error_count:
            self.message_user(request, f"{error_count} Produkt(e) mit Fehlern.", level=messages.ERROR)

    @action(
        description="Sync to Shopware6",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_shopware_detail(self, request, object_id: str):
        product = self.get_object(request, object_id)
        if not product:
            self.message_user(request, "Produkt nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)
        try:
            success_count, error_count = self._sync_products_bulk([product], ProductService(), request=request)
            if success_count:
                self.message_user(request, f"Produkt {product.erp_nr} synchronisiert.")
            if error_count:
                self.message_user(request, "Sync fehlgeschlagen.", level=messages.ERROR)
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Shopware sync failed for {product.erp_nr}: {exc}",
                obj=product,
            )
            self.message_user(request, f"Sync fehlgeschlagen: {exc}", level=messages.ERROR)
        return self._redirect_to_change_page(object_id)


@admin.register(Price)
class PriceAdmin(BaseAdmin):
    list_display = ("product", "sales_channel", "price", "special_price", "special_active", "rebate_price", "created_at")
    search_fields = ("product__erp_nr", "product__name", "sales_channel__name")
    list_filter = ("sales_channel", "created_at")

    @admin.display(boolean=True, description="Sonderpreis aktiv")
    def special_active(self, obj: Price) -> bool:
        return obj.is_special_active
