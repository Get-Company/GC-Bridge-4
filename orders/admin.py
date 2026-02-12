from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from orders.models import Order, OrderDetail
from orders.services import OrderSyncService


class OrderDetailInline(BaseTabularInline):
    model = OrderDetail
    fields = (
        "erp_nr",
        "name",
        "quantity",
        "unit_price",
        "total_price",
        "tax",
        "created_at",
        "updated_at",
    )


@admin.register(Order)
class OrderAdmin(BaseAdmin):
    list_display = (
        "order_number",
        "api_id",
        "customer",
        "order_state",
        "payment_state",
        "shipping_state",
        "total_price",
        "purchase_date",
        "created_at",
    )
    search_fields = ("order_number", "api_id", "customer__erp_nr", "customer__email")
    list_filter = ("order_state", "payment_state", "shipping_state", "created_at")
    inlines = (OrderDetailInline,)
    actions_list = ("sync_open_orders_from_shopware_list",)
    actions = ("sync_open_orders_from_shopware",)

    def _redirect_to_changelist(self) -> HttpResponseRedirect:
        return HttpResponseRedirect(reverse("admin:orders_order_changelist"))

    def _run_open_order_sync(self, request) -> None:
        try:
            summary = OrderSyncService().sync_open_orders()
        except Exception as exc:
            self.message_user(request, f"Order-Sync fehlgeschlagen: {exc}", level=messages.ERROR)
            return

        self.message_user(
            request,
            (
                f"Orders gesehen: {summary['orders_seen']}, erstellt: {summary['orders_created']}, "
                f"aktualisiert: {summary['orders_updated']}, Details: {summary['details_upserted']}, "
                f"Fehler: {summary['orders_failed']}"
            ),
        )

    @action(
        description="Sync Open Orders From Shopware",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_open_orders_from_shopware_list(self, request):
        self._run_open_order_sync(request)
        return self._redirect_to_changelist()

    @action(
        description="Sync Open Orders From Shopware",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_open_orders_from_shopware(self, request, queryset):
        self._run_open_order_sync(request)


@admin.register(OrderDetail)
class OrderDetailAdmin(BaseAdmin):
    list_display = ("order", "erp_nr", "name", "quantity", "unit_price", "total_price", "created_at")
    search_fields = ("order__order_number", "order__api_id", "erp_nr", "name")
    list_filter = ("created_at",)
