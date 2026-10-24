import hashlib
import logging

from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    FieldTextFilter,
    RangeDateTimeFilter,
)
from unfold.decorators import action
from unfold.enums import ActionVariant
from unfold.forms import BaseDialogForm

from core.admin import BaseAdmin
from emails.models import EmailCampaign, EmailCampaignQueueEntry
from emails.services import EmailCampaignQueueService
from newsletter.models import NewsletterRecipient, NewsletterRecipientGroup
from newsletter.services import NewsletterRecipientSyncService

logger = logging.getLogger(__name__)


def _group_test_selection_fingerprint(group: NewsletterRecipientGroup) -> str:
    campaign_id = group.test_email_campaign_id or ""
    campaign_updated_at = (
        group.test_email_campaign.updated_at.isoformat() if group.test_email_campaign_id else ""
    )
    members = list(
        group.members.order_by("pk").values_list("pk", "email", "status", "is_present_in_shopware")
    )
    selection = f"{campaign_id}:{campaign_updated_at}:{members!r}"
    return hashlib.sha256(selection.encode("utf-8")).hexdigest()


class RecipientGroupFilter(admin.SimpleListFilter):
    title = "Empfängerkreis"
    parameter_name = "recipient_group"

    def lookups(self, request, model_admin):
        return list(NewsletterRecipientGroup.objects.order_by("name").values_list("pk", "name"))

    def queryset(self, request, queryset):
        group_id = self.value()
        if group_id is None:
            return queryset
        if not group_id.isdecimal():
            return queryset.none()
        return queryset.filter(recipient_groups__pk=int(group_id))


class QueueGroupTestForm(BaseDialogForm):
    confirm = forms.BooleanField(label="Test-Warteschlange bestätigen", required=True)
    selection_fingerprint = forms.CharField(widget=forms.HiddenInput, required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        group = (
            NewsletterRecipientGroup.objects.select_related("test_email_campaign")
            .filter(pk=self.object_id)
            .first()
        )
        self.group = group
        if group is None:
            return
        member_emails = list(group.members.order_by("pk").values_list("email", flat=True))
        member_count = len(member_emails)
        campaign = group.test_email_campaign
        campaign_label = campaign.internal_title if campaign else "keine Kampagne ausgewählt"
        if not self.is_bound:
            self.initial["selection_fingerprint"] = _group_test_selection_fingerprint(group)
        self.fields["confirm"].label = (
            f"Test-E-Mails „{campaign_label}“ für bis zu {member_count} Gruppenmitglieder einreihen"
        )
        if member_count <= 20:
            self.fields["confirm"].help_text = "Mitglieder: " + (
                ", ".join(member_emails) if member_emails else "keine"
            )

    def clean_selection_fingerprint(self):
        if self.group is None:
            raise forms.ValidationError("Empfängerkreis nicht gefunden.")
        expected = _group_test_selection_fingerprint(self.group)
        if self.cleaned_data["selection_fingerprint"] != expected:
            raise forms.ValidationError(
                "Kampagne oder Gruppenmitglieder haben sich geändert. Bitte den Dialog neu öffnen."
            )
        return expected


@admin.register(NewsletterRecipient)
class NewsletterRecipientAdmin(BaseAdmin):
    list_display = (
        "email",
        "salutation_display_name",
        "full_name",
        "status_badge",
        "customer_badge",
        "erp_nr",
        "recipient_groups_display",
        "selected_email_campaign",
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
        "erp_nr",
        "customer__erp_nr",
        "customer__name",
        "customer__email",
        "selected_email_campaign__internal_title",
        "recipient_groups__name",
        "sales_channel_id",
    )
    list_filter = [
        ("status", FieldTextFilter),
        RecipientGroupFilter,
        ("is_customer", BooleanRadioFilter),
        ("sales_channel_id", FieldTextFilter),
        ("is_present_in_shopware", BooleanRadioFilter),
        ("last_synced_at", RangeDateTimeFilter),
    ]
    readonly_fields = BaseAdmin.readonly_fields + (
        "shopware_id",
        "customer_shopware_id",
        "erp_nr",
        "customer",
        "is_customer",
        "last_synced_at",
        "remote_created_at",
        "remote_updated_at",
        "raw_data",
    )
    actions_list = ("sync_from_shopware_list", "relink_customers_list")
    actions_submit_line = ("queue_selected_campaign_submit",)
    actions = ("queue_selected_campaign", "sync_from_shopware", "relink_customers")
    autocomplete_fields = ("selected_email_campaign",)

    status_badge_map = {
        NewsletterRecipient.Status.DIRECT: ("#16a34a", "Aktiv", "direkt aktiv, keine Bestaetigung offen"),
        NewsletterRecipient.Status.OPT_IN: ("#16a34a", "Aktiv", "Double-Opt-In bestaetigt"),
        NewsletterRecipient.Status.OPT_OUT: ("#dc2626", "Nicht aktiv", "abgemeldet"),
        NewsletterRecipient.Status.NOT_SET: ("#ca8a04", "Ausstehend", "wartet auf Bestaetigung"),
    }

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("customer", "selected_email_campaign")
            .prefetch_related("recipient_groups")
        )

    @admin.display(description="Empfängerkreise")
    def recipient_groups_display(self, obj: NewsletterRecipient):
        groups = obj.recipient_groups.all()
        if not groups:
            return "—"
        return format_html_join(
            ", ",
            '<a href="{}">{}</a>',
            (
                (reverse("admin:newsletter_newsletterrecipientgroup_change", args=(group.pk,)), group.name)
                for group in groups
            ),
        )

    def _redirect_to_change_page(self, object_id: str):
        return HttpResponseRedirect(reverse("admin:newsletter_newsletterrecipient_change", args=(object_id,)))

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
                '<span style="color:#dc2626;font-weight:600;white-space:nowrap;">{}</span>',
                "Nein",
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
            summary = NewsletterRecipientSyncService().sync_from_shopware(mark_missing=True)
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
                f"{summary['linked']} Kunden zugeordnet, "
                f"{summary['unlinked']} ohne Kundenzuordnung, "
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

    def _run_relink_customers(self, request) -> None:
        summary = NewsletterRecipientSyncService().relink_existing()
        self.message_user(
            request,
            (
                "Kundenzuordnung aktualisiert: "
                f"{summary['seen']} geprueft, "
                f"{summary['updated']} aktualisiert, "
                f"{summary['linked']} zugeordnet, "
                f"{summary['unlinked']} ohne Zuordnung."
            ),
        )

    @action(
        description="Kundenzuordnungen aus AdrNr neu aufbauen",
        icon="link",
        variant=ActionVariant.DEFAULT,
    )
    def relink_customers_list(self, request):
        self._run_relink_customers(request)
        return self._redirect_to_changelist()

    @action(
        description="Kundenzuordnungen aus AdrNr neu aufbauen",
        icon="link",
        variant=ActionVariant.DEFAULT,
    )
    def relink_customers(self, request, queryset):
        self._run_relink_customers(request)

    def _queue_recipients(self, request, recipients) -> None:
        service = EmailCampaignQueueService()
        queued_count = 0
        already_count = 0
        error_count = 0

        for recipient in recipients:
            try:
                was_queued = (
                    recipient.selected_email_campaign_id is not None
                    and EmailCampaignQueueEntry.objects.filter(
                        campaign_id=recipient.selected_email_campaign_id,
                        recipient=recipient,
                    ).exists()
                )
                service.queue_recipient_campaign(recipient)
                if was_queued:
                    already_count += 1
                else:
                    queued_count += 1
            except Exception as exc:
                error_count += 1
                self.message_user(
                    request,
                    f"{recipient.email}: Kampagne konnte nicht eingereiht werden: {exc}",
                    level=messages.ERROR,
                )

        if queued_count:
            self.message_user(
                request,
                f"{queued_count} E-Mail(s) neu gerendert und in die Warteschlange gelegt.",
                level=messages.SUCCESS,
            )
        if already_count:
            self.message_user(
                request,
                f"{already_count} E-Mail(s) bereits vorhanden; keine erneute Einreihung.",
                level=messages.INFO,
            )
        if error_count:
            self.message_user(request, f"{error_count} Empfaenger mit Fehlern.", level=messages.ERROR)

    @action(
        description="Ausgewaehlte Kampagne in Warteschlange legen",
        icon="outbox",
        variant=ActionVariant.PRIMARY,
    )
    def queue_selected_campaign_submit(self, request, obj: NewsletterRecipient):
        recipient = obj
        if not recipient:
            self.message_user(request, "Newsletter-Empfaenger nicht gefunden.", level=messages.ERROR)
            return
        self._queue_recipients(request, [recipient])

    def response_change(self, request, obj):
        action_name = self.get_unfold_action("queue_selected_campaign_submit").action_name
        if action_name in request.POST:
            return self._redirect_to_change_page(str(obj.pk))
        return super().response_change(request, obj)

    @action(
        description="Ausgewaehlte Kampagne in Warteschlange legen",
        icon="outbox",
        variant=ActionVariant.PRIMARY,
    )
    def queue_selected_campaign(self, request, queryset):
        self._queue_recipients(
            request,
            queryset.select_related("customer", "selected_email_campaign").prefetch_related(
                "customer__addresses"
            ),
        )


@admin.register(NewsletterRecipientGroup)
class NewsletterRecipientGroupAdmin(BaseAdmin):
    list_display = ("name", "member_count", "test_email_campaign", "description", "created_at")
    search_fields = ("name", "description", "members__email")
    autocomplete_fields = ("members", "test_email_campaign")
    readonly_fields = BaseAdmin.readonly_fields + ("member_count",)
    fields = ("name", "description", "test_email_campaign", "members", "member_count", "created_at", "updated_at")
    actions_detail = ("queue_group_test_detail",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_member_count=Count("members", distinct=True))

    @admin.display(description="Mitglieder", ordering="_member_count")
    def member_count(self, obj: NewsletterRecipientGroup):
        if obj is None:
            return "—"
        count = getattr(obj, "_member_count", None)
        if count is None:
            count = obj.members.count()
        url = reverse("admin:newsletter_newsletterrecipient_changelist")
        return format_html('<a href="{}?recipient_group={}">{}</a>', url, obj.pk, count)

    @action(
        description="Test-E-Mails des Kreises einreihen",
        icon="outbox",
        variant=ActionVariant.PRIMARY,
        permissions=("change", "queue_test"),
        dialog={
            "title": "Test-E-Mails des Empfängerkreises einreihen",
            "description": (
                "Die gespeicherte Entwurfs-Kampagne wird nur für Mitglieder dieses Kreises "
                "in dieselbe Warteschlange wie der Serienversand gelegt (höchstens 20 Empfänger). "
                "Der Serienversand wird dadurch nicht gestartet."
            ),
            "form_class": QueueGroupTestForm,
            "form_submit_text": "Test-E-Mails einreihen",
        },
    )
    def queue_group_test_detail(self, request, form: QueueGroupTestForm, object_id: str):
        from emails.services import EmailCampaignTestQueueService, EmailSmtpSettingsError

        group = self.get_object(request, object_id)
        if group is None:
            self.message_user(request, "Empfängerkreis nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_changelist()
        campaign = group.test_email_campaign
        if campaign is None or campaign.status != EmailCampaign.Status.DRAFT:
            self.message_user(
                request,
                "Bitte zuerst eine Entwurfs-Kampagne für den Test am Empfängerkreis speichern.",
                level=messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse("admin:newsletter_newsletterrecipientgroup_change", args=(group.pk,))
            )

        try:
            summary = EmailCampaignTestQueueService().queue_group(campaign=campaign, group=group)
        except (ValueError, EmailSmtpSettingsError) as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(
                reverse("admin:newsletter_newsletterrecipientgroup_change", args=(group.pk,))
            )
        except Exception:
            logger.exception("Test-Warteschlange für Empfängerkreis %s fehlgeschlagen", group.pk)
            self.message_user(
                request,
                "Test-E-Mails konnten nicht eingereiht werden. Bitte Server-Log prüfen.",
                level=messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse("admin:newsletter_newsletterrecipientgroup_change", args=(group.pk,))
            )

        queued = summary["queued"]
        skipped = summary["skipped"]
        failed = summary["failed"]
        self.message_user(
            request,
            (
                f"Testkreis „{group.name}“: {queued} eingereiht, "
                f"{skipped} übersprungen, {failed} fehlgeschlagen."
            ),
            level=(
                messages.SUCCESS if queued > 0 and failed == 0
                else messages.INFO if failed == 0
                else messages.ERROR
            ),
        )
        for error in summary.get("errors", [])[:5]:
            self.message_user(request, str(error), level=messages.ERROR)
        if queued > 0:
            try:
                from emails.tasks import send_due_campaign_queue

                send_due_campaign_queue.delay()
            except Exception:
                logger.exception("Sofortiger Test-Queue-Start für Empfängerkreis %s fehlgeschlagen", group.pk)
                self.message_user(
                    request,
                    "Test-E-Mails sind eingereiht; der sofortige Worker-Start schlug fehl. "
                    "Der reguläre Worker prüft die Warteschlange spätestens beim nächsten Lauf.",
                    level=messages.WARNING,
                )
        return HttpResponseRedirect(
            reverse("admin:newsletter_newsletterrecipientgroup_change", args=(group.pk,))
        )

    def has_queue_test_permission(self, request, obj=None):
        return request.user.has_perm("newsletter.view_newsletterrecipient") and request.user.has_perm(
            "emails.change_emailcampaign"
        )
