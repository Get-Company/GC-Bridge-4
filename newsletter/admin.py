from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    FieldTextFilter,
    RangeDateTimeFilter,
)
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin
from newsletter.models import NewsletterRecipient
from newsletter.services import NewsletterRecipientSyncService


@admin.register(NewsletterRecipient)
class NewsletterRecipientAdmin(BaseAdmin):
    list_display = (
        "email",
        "salutation_display_name",
        "full_name",
        "status_badge",
        "customer_badge",
        "city",
        "sales_channel_id",
        "last_synced_at",
    )
    search_fields = (
        "email",
        "salutation_display_name",
        "salutation_letter_name",
        "first_name",
        "last_name",
        "city",
        "shopware_id",
        "customer_shopware_id",
        "customer__erp_nr",
        "customer__name",
        "customer__email",
        "sales_channel_id",
    )
    list_filter = [
        ("status", FieldTextFilter),
        ("is_customer", BooleanRadioFilter),
        ("sales_channel_id", FieldTextFilter),
        ("is_present_in_shopware", BooleanRadioFilter),
        ("last_synced_at", RangeDateTimeFilter),
    ]
    readonly_fields = BaseAdmin.readonly_fields + (
        "shopware_id",
        "customer_shopware_id",
        "customer",
        "is_customer",
        "last_synced_at",
        "remote_created_at",
        "remote_updated_at",
        "raw_data",
    )
    actions_list = ("sync_from_shopware_list",)
    actions = ("sync_from_shopware",)

    status_badge_map = {
        NewsletterRecipient.Status.DIRECT: ("#16a34a", "Aktiv", "direkt aktiv, keine Bestaetigung offen"),
        NewsletterRecipient.Status.OPT_IN: ("#16a34a", "Aktiv", "Double-Opt-In bestaetigt"),
        NewsletterRecipient.Status.OPT_OUT: ("#dc2626", "Nicht aktiv", "abgemeldet"),
        NewsletterRecipient.Status.NOT_SET: ("#ca8a04", "Ausstehend", "wartet auf Bestaetigung"),
    }

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("customer")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: NewsletterRecipient):
        color, state, note = self.status_badge_map.get(
            obj.status,
            ("#6b7280", "Unbekannt", "Status nicht bekannt"),
        )
        raw_status = obj.status or "unbekannt"
        return format_html(
            (
                '<span title="{}" style="display:inline-flex;align-items:center;gap:6px;'
                'padding:2px 8px;border-radius:999px;background:{}1a;color:{};'
                'font-weight:600;white-space:nowrap;">'
                '<span style="width:8px;height:8px;border-radius:999px;background:{};"></span>'
                '{} · {} · {}'
                '</span>'
            ),
            note,
            color,
            color,
            color,
            raw_status,
            state,
            note,
        )

    @admin.display(description="Kunde", ordering="is_customer")
    def customer_badge(self, obj: NewsletterRecipient):
        if not obj.customer_id:
            return format_html(
                '<span style="color:#dc2626;font-weight:600;white-space:nowrap;">Nein</span>'
            )

        url = reverse("admin:customer_customer_change", args=(obj.customer_id,))
        return format_html(
            '<a href="{}" style="color:#16a34a;font-weight:600;white-space:nowrap;">Ja · {} · {}</a>',
            url,
            obj.customer.erp_nr,
            obj.customer.name or obj.customer.email or obj.customer.api_id,
        )

    def _run_sync_from_shopware(self, request) -> None:
        try:
            summary = NewsletterRecipientSyncService().sync_from_shopware()
        except Exception as exc:
            self.message_user(
                request,
                f"Newsletter-Sync fehlgeschlagen: {exc}",
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            (
                "Newsletter-Sync abgeschlossen: "
                f"{summary['seen']} gesehen, "
                f"{summary['created']} neu, "
                f"{summary['updated']} aktualisiert, "
                f"{summary['failed']} Fehler."
            ),
        )

    @action(
        description="Newsletter-Empfaenger von Shopware synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_shopware_list(self, request):
        self._run_sync_from_shopware(request)
        return self._redirect_to_changelist()

    @action(
        description="Newsletter-Empfaenger von Shopware synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_shopware(self, request, queryset):
        self._run_sync_from_shopware(request)
