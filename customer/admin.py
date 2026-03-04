from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    FieldTextFilter,
    RangeDateTimeFilter,
)
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from customer.models import Address, Customer
from microtech.models import MicrotechJob
from microtech.services import MicrotechQueueService


class AddressInline(BaseTabularInline):
    model = Address
    fields = (
        "erp_ans_id",
        "name1",
        "name2",
        "street",
        "postal_code",
        "city",
        "country_code",
        "email",
        "is_invoice",
        "is_shipping",
        "created_at",
        "updated_at",
    )


@admin.register(Customer)
class CustomerAdmin(BaseAdmin):
    list_display = ("erp_nr", "name", "email", "is_gross", "created_at")
    search_fields = ("erp_nr", "name", "email")
    list_filter = [
        ("is_gross", BooleanRadioFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    inlines = (AddressInline,)
    actions = ("sync_from_microtech", "sync_to_microtech")
    actions_detail = ("sync_from_microtech_detail", "sync_to_microtech_detail")

    def _redirect_to_change_page(self, object_id: str) -> HttpResponseRedirect:
        return HttpResponseRedirect(reverse("admin:customer_customer_change", args=(object_id,)))

    @action(
        description="Von Microtech synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_microtech(self, request, queryset):
        queue = MicrotechQueueService()
        queued_count = 0
        error_count = 0

        for customer in queryset:
            if not customer.erp_nr:
                error_count += 1
                continue
            try:
                queue.enqueue(
                    job_type=MicrotechJob.JobType.SYNC_CUSTOMER,
                    payload={"erp_nr": customer.erp_nr},
                    priority=25,
                    created_by_id=getattr(request.user, "id", None),
                )
                queued_count += 1
            except Exception as exc:
                error_count += 1
                self.message_user(
                    request,
                    f"Einreihen fehlgeschlagen fuer Kunde {customer.erp_nr}: {exc}",
                    level=messages.ERROR,
                )

        if queued_count:
            self.message_user(request, f"{queued_count} Kunde(n) fuer Microtech-Sync eingereiht.")
        if error_count:
            self.message_user(request, f"{error_count} Kunde(n) mit Fehlern.", level=messages.ERROR)

    @action(
        description="Nach Microtech übertragen",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_microtech(self, request, queryset):
        queue = MicrotechQueueService()
        queued_count = 0
        error_count = 0

        for customer in queryset:
            try:
                queue.enqueue(
                    job_type=MicrotechJob.JobType.UPSERT_CUSTOMER,
                    payload={"customer_id": customer.id},
                    priority=30,
                    created_by_id=getattr(request.user, "id", None),
                )
                queued_count += 1
            except Exception as exc:
                error_count += 1
                self.message_user(
                    request,
                    f"Einreihen nach Microtech fehlgeschlagen fuer Kunde {customer.erp_nr or customer.id}: {exc}",
                    level=messages.ERROR,
                )

        if queued_count:
            self.message_user(request, f"{queued_count} Kunde(n) fuer Microtech-Upsert eingereiht.")
        if error_count:
            self.message_user(request, f"{error_count} Kunde(n) mit Fehlern.", level=messages.ERROR)

    @action(
        description="Von Microtech synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_microtech_detail(self, request, object_id: str):
        customer = self.get_object(request, object_id)
        if not customer:
            self.message_user(request, "Kunde nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)
        if not customer.erp_nr:
            self.message_user(request, "Der Kunde hat keine ERP-Nummer.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)

        try:
            MicrotechQueueService().enqueue(
                job_type=MicrotechJob.JobType.SYNC_CUSTOMER,
                payload={"erp_nr": customer.erp_nr},
                priority=25,
                created_by_id=getattr(request.user, "id", None),
            )
            self.message_user(request, f"Kunde {customer.erp_nr} fuer Sync eingereiht.")
        except Exception as exc:
            self.message_user(
                request,
                f"Sync-Einreihung fehlgeschlagen fuer Kunde {customer.erp_nr}: {exc}",
                level=messages.ERROR,
            )

        return self._redirect_to_change_page(object_id)

    @action(
        description="Nach Microtech übertragen",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_microtech_detail(self, request, object_id: str):
        customer = self.get_object(request, object_id)
        if not customer:
            self.message_user(request, "Kunde nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)

        try:
            MicrotechQueueService().enqueue(
                job_type=MicrotechJob.JobType.UPSERT_CUSTOMER,
                payload={"customer_id": customer.id},
                priority=30,
                created_by_id=getattr(request.user, "id", None),
            )
            self.message_user(
                request,
                f"Kunde {customer.erp_nr or customer.id} fuer Microtech-Upsert eingereiht.",
            )
        except Exception as exc:
            self.message_user(
                request,
                f"Upsert-Einreihung fehlgeschlagen fuer Kunde {customer.erp_nr or customer.id}: {exc}",
                level=messages.ERROR,
            )

        return self._redirect_to_change_page(object_id)


@admin.register(Address)
class AddressAdmin(BaseAdmin):
    list_display = ("customer", "erp_ans_id", "name1", "city", "is_invoice", "is_shipping", "created_at")
    search_fields = ("customer__erp_nr", "name1", "name2", "street", "postal_code", "city")
    list_filter = [
        ("is_invoice", BooleanRadioFilter),
        ("is_shipping", BooleanRadioFilter),
        ("country_code", FieldTextFilter),
        ("created_at", RangeDateTimeFilter),
    ]
