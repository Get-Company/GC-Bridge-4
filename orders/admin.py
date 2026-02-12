import json
from typing import Any

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from orders.models import Order, OrderDetail
from orders.services import OrderSyncService
from shopware.services import OrderService
from shopware.services.order import DEFAULT_TRANSITION_ACTIONS


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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
        "order_state_dropdown",
        "payment_state_dropdown",
        "shipping_state_dropdown",
        "total_price",
        "purchase_date",
        "created_at",
    )
    search_fields = ("order_number", "api_id", "customer__erp_nr", "customer__email")
    list_filter = ("order_state", "payment_state", "shipping_state", "created_at")
    inlines = (OrderDetailInline,)
    actions_list = ("sync_open_orders_from_shopware_list",)
    actions = ("sync_open_orders_from_shopware",)
    list_fullwidth = True

    class Media:
        js = ("orders/js/order_state_controls.js",)

    def _redirect_to_changelist(self) -> HttpResponseRedirect:
        return HttpResponseRedirect(reverse("admin:orders_order_changelist"))

    def get_custom_urls(self):
        urls = super().get_custom_urls()
        return (
            *urls,
            (
                "<path:object_id>/shopware-state-options/",
                "orders_order_state_options",
                self.shopware_state_options_view,
            ),
            (
                "<path:object_id>/shopware-set-state/",
                "orders_order_set_state",
                self.shopware_set_state_view,
            ),
        )

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

    @admin.display(description="Order Status")
    def order_state_dropdown(self, obj: Order) -> str:
        return self._render_state_dropdown(obj=obj, scope="order", current_state=obj.order_state)

    @admin.display(description="Payment Status")
    def payment_state_dropdown(self, obj: Order) -> str:
        return self._render_state_dropdown(obj=obj, scope="payment", current_state=obj.payment_state)

    @admin.display(description="Delivery Status")
    def shipping_state_dropdown(self, obj: Order) -> str:
        return self._render_state_dropdown(obj=obj, scope="delivery", current_state=obj.shipping_state)

    def _render_state_dropdown(self, *, obj: Order, scope: str, current_state: str) -> str:
        options_url = reverse("admin:orders_order_state_options", args=(obj.pk,))
        set_url = reverse("admin:orders_order_set_state", args=(obj.pk,))
        has_entity_id = bool(self._state_entity_id(order=obj, scope=scope))

        fallback = DEFAULT_TRANSITION_ACTIONS.get(scope, [])
        options = [("", "Status waehlen..."), *((action, action.replace("_", " ")) for action in fallback)]
        if not has_entity_id:
            options = [("", "Keine API-ID vorhanden")]
        options_html = format_html_join("", '<option value="{}">{}</option>', options)

        return format_html(
            (
                '<div class="js-sw-state-control" data-scope="{}" data-options-url="{}" data-set-url="{}">'
                '<span class="js-sw-state-current">{}</span><br>'
                '<select class="js-sw-state-select" data-scope="{}" {}>{}</select>'
                "</div>"
            ),
            scope,
            options_url,
            set_url,
            current_state or "-",
            scope,
            "disabled" if not has_entity_id else "",
            options_html,
        )

    def shopware_state_options_view(self, request, object_id: str, **kwargs):
        order = self.get_object(request, object_id)
        if not order:
            return JsonResponse({"ok": False, "error": "Order not found."}, status=404)
        if not self.has_change_permission(request, order):
            return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

        scope = _to_str(request.GET.get("scope") or request.GET.get("kind")).lower()
        if scope not in {"order", "payment", "delivery"}:
            return JsonResponse({"ok": False, "error": "Invalid scope."}, status=400)

        entity_id = self._state_entity_id(order=order, scope=scope)
        if not entity_id:
            return JsonResponse(
                {"ok": False, "error": f"Order has no API id for scope '{scope}'."},
                status=400,
            )

        actions = OrderService().get_available_transition_actions(scope=scope, entity_id=entity_id)
        return JsonResponse({"ok": True, "scope": scope, "actions": actions})

    def shopware_set_state_view(self, request, object_id: str, **kwargs):
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": "POST required."}, status=405)

        order = self.get_object(request, object_id)
        if not order:
            return JsonResponse({"ok": False, "error": "Order not found."}, status=404)
        if not self.has_change_permission(request, order):
            return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError):
            payload = {}

        scope = _to_str(payload.get("scope") or payload.get("kind")).lower()
        action_name = _to_str(payload.get("action"))

        if scope not in {"order", "payment", "delivery"}:
            return JsonResponse({"ok": False, "error": "Invalid scope."}, status=400)
        if not action_name:
            return JsonResponse({"ok": False, "error": "Action is required."}, status=400)

        service = OrderService()

        try:
            if scope == "order":
                service.set_order_state(order_id=order.api_id, action_name=action_name)
            elif scope == "delivery":
                service.set_delivery_state(delivery_id=order.api_delivery_id, action_name=action_name)
            else:
                service.set_transaction_state(
                    transaction_id=order.api_transaction_id,
                    action_name=action_name,
                )
        except Exception as exc:  # pragma: no cover - remote runtime errors
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)

        self._refresh_local_states(order=order, service=service)

        return JsonResponse(
            {
                "ok": True,
                "scope": scope,
                "order_state": order.order_state,
                "payment_state": order.payment_state,
                "shipping_state": order.shipping_state,
            }
        )

    @staticmethod
    def _state_entity_id(*, order: Order, scope: str) -> str:
        if scope == "order":
            return _to_str(order.api_id)
        if scope == "delivery":
            return _to_str(order.api_delivery_id)
        return _to_str(order.api_transaction_id)

    def _refresh_local_states(self, *, order: Order, service: OrderService) -> None:
        response = service.get_by_id(order.api_id)
        rows = (response or {}).get("data", []) or []
        if not rows:
            return

        sw_order = self._as_entity(rows[0])
        order_state = self._extract_state_name(sw_order)
        deliveries = self._as_entity_list(sw_order.get("deliveries"))
        transactions = self._as_entity_list(sw_order.get("transactions"))
        shipping_state = self._extract_state_name(deliveries[0]) if deliveries else ""
        payment_state = self._extract_state_name(transactions[0]) if transactions else ""

        update_fields: list[str] = []
        if order_state and order.order_state != order_state:
            order.order_state = order_state
            update_fields.append("order_state")
        if shipping_state and order.shipping_state != shipping_state:
            order.shipping_state = shipping_state
            update_fields.append("shipping_state")
        if payment_state and order.payment_state != payment_state:
            order.payment_state = payment_state
            update_fields.append("payment_state")

        if update_fields:
            update_fields.append("updated_at")
            order.save(update_fields=update_fields)

    @staticmethod
    def _as_entity(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        entity = dict(payload)
        attributes = payload.get("attributes")
        if isinstance(attributes, dict):
            for key, value in attributes.items():
                entity.setdefault(key, value)
        return entity

    @classmethod
    def _as_entity_list(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [cls._as_entity(item) for item in payload]
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return [cls._as_entity(item) for item in data]
            attrs = payload.get("attributes")
            if isinstance(attrs, dict):
                nested = attrs.get("data")
                if isinstance(nested, list):
                    return [cls._as_entity(item) for item in nested]
        return []

    @classmethod
    def _extract_state_name(cls, payload: Any) -> str:
        entity = cls._as_entity(payload)
        state = cls._as_entity(entity.get("stateMachineState"))
        return _to_str(state.get("technicalName") or state.get("name"))


@admin.register(OrderDetail)
class OrderDetailAdmin(BaseAdmin):
    list_display = ("order", "erp_nr", "name", "quantity", "unit_price", "total_price", "created_at")
    search_fields = ("order__order_number", "order__api_id", "erp_nr", "name")
    list_filter = ("created_at",)
