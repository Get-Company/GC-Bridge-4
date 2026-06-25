from django.contrib import admin, messages

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
        "full_name",
        "status",
        "city",
        "sales_channel_id",
        "is_present_in_shopware",
        "last_synced_at",
    )
    search_fields = (
        "email",
        "first_name",
        "last_name",
        "city",
        "shopware_id",
        "sales_channel_id",
    )
    list_filter = [
        ("status", FieldTextFilter),
        ("sales_channel_id", FieldTextFilter),
        ("is_present_in_shopware", BooleanRadioFilter),
        ("last_synced_at", RangeDateTimeFilter),
    ]
    readonly_fields = BaseAdmin.readonly_fields + (
        "shopware_id",
        "last_synced_at",
        "remote_created_at",
        "remote_updated_at",
        "raw_data",
    )
    actions_list = ("sync_from_shopware_list",)
    actions = ("sync_from_shopware",)

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
