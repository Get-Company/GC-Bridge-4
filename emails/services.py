from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_UP

from django.core.mail import get_connection
from django.db import transaction
from django.utils import timezone

from core.services import BaseService
from emails.mjml import compile_mjml_to_html, html_to_plain_text, render_campaign_mjml
from emails.models import (
    EmailCampaign,
    EmailCampaignPriceState,
    EmailCampaignQueueEntry,
    EmailSmtpSettings,
)

logger = logging.getLogger(__name__)


class EmailSmtpSettingsError(RuntimeError):
    pass


class EmailSmtpSettingsService(BaseService):
    model = EmailSmtpSettings

    @staticmethod
    def build_connection(configuration: EmailSmtpSettings):
        if not configuration.smtp_is_configured:
            raise EmailSmtpSettingsError("Die SMTP-Konfiguration ist unvollständig.")
        return get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=configuration.host,
            port=configuration.port,
            username=configuration.username or None,
            password=configuration.password or None,
            use_tls=configuration.security == EmailSmtpSettings.Security.STARTTLS,
            use_ssl=configuration.security == EmailSmtpSettings.Security.SSL,
            timeout=configuration.timeout,
        )

    def test_connection(self, configuration: EmailSmtpSettings) -> None:
        connection = self.build_connection(configuration)
        try:
            connection.open()
        finally:
            connection.close()


def _round_up_5ct(value: Decimal) -> Decimal:
    step = Decimal("0.05")
    return (Decimal(value) / step).to_integral_value(rounding=ROUND_UP) * step


def _apply_channel_factor(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    return _round_up_5ct(Decimal(value) * factor).quantize(Decimal("0.01"))


def _end_of_next_month(now) -> object:
    next_month = (now.month % 12) + 1
    year = now.year + (1 if next_month == 1 else 0)
    last_day = calendar.monthrange(year, next_month)[1]
    return now.replace(
        year=year, month=next_month, day=last_day,
        hour=23, minute=59, second=59, microsecond=0,
    )


class EmailCampaignPriceSyncService(BaseService):
    """Apply campaign specials and retain enough state to undo removed products."""

    model = EmailCampaignPriceState
    tracked_price_fields = (
        "special_percentage",
        "special_price",
        "special_start_date",
        "special_end_date",
    )

    @transaction.atomic
    def reconcile(self, campaign: EmailCampaign) -> list[str]:
        from products.models import Price, Product
        from products.services.product_auto_sync import disable_product_auto_sync
        from shopware.models import ShopwareSettings

        default_channel = (
            ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
        )
        if default_channel is None:
            return []

        desired = {
            item.product_id: item
            for item in campaign.campaign_products.select_related("product").all()
            if item.special_price_override is not None or item.discount_pct is not None
        }
        owned_states = {
            state.product_id: state
            for state in self.model.objects.select_for_update()
            .filter(campaign=campaign)
            .select_related("product")
        }
        affected: set[str] = set()

        with disable_product_auto_sync():
            for product_id in owned_states.keys() - desired.keys():
                state = owned_states[product_id]
                if self._restore_snapshot(state, price_model=Price):
                    affected.add(state.product.erp_nr)
                state.delete()

            for product_id, item in desired.items():
                # Serialize competing campaign claims for the same product. The
                # state row may not exist yet, so locking only that table is not
                # sufficient to prevent concurrent first-time claims.
                Product.objects.select_for_update().get(pk=product_id)
                prices = list(
                    Price.objects.filter(
                        product_id=product_id,
                        sales_channel__is_active=True,
                    ).select_related("sales_channel")
                )
                default_price = next(
                    (price for price in prices if price.sales_channel_id == default_channel.pk),
                    None,
                )
                if default_price is None:
                    continue

                state = (
                    self.model.objects.select_for_update()
                    .filter(product_id=product_id)
                    .select_related("product")
                    .first()
                )
                if state is None:
                    state = self.model.objects.create(
                        campaign=campaign,
                        product_id=product_id,
                        price_snapshot=self._snapshot_prices(prices),
                    )
                else:
                    intent_at = max(campaign.updated_at, item.updated_at)
                    if state.campaign_id != campaign.pk and state.updated_at > intent_at:
                        # A newer save from another campaign already owns this
                        # product. A delayed Celery task must not take it back.
                        continue
                    snapshot = self._extend_snapshot(state.price_snapshot, prices)
                    state_changed = (
                        state.campaign_id != campaign.pk
                        or snapshot != state.price_snapshot
                    )
                    state.campaign = campaign
                    state.price_snapshot = snapshot
                    if state_changed:
                        state.save(update_fields=("campaign", "price_snapshot", "updated_at"))

                special_price = self._special_price(item, default_price)
                changed = self._apply_special_price(
                    prices=prices,
                    default_channel_id=default_channel.pk,
                    special_price=special_price,
                )
                if changed:
                    affected.add(item.product.erp_nr)
                campaign.campaign_products.filter(pk=item.pk).update(
                    prices_synced_at=timezone.now()
                )

        return sorted(affected)

    @transaction.atomic
    def release(self, campaign: EmailCampaign) -> list[str]:
        """Restore every price still owned by a campaign before it is deleted."""
        from products.models import Price
        from products.services.product_auto_sync import disable_product_auto_sync

        states = list(
            self.model.objects.select_for_update()
            .filter(campaign=campaign)
            .select_related("product")
        )
        affected: set[str] = set()
        with disable_product_auto_sync():
            for state in states:
                if self._restore_snapshot(state, price_model=Price):
                    affected.add(state.product.erp_nr)
                state.delete()
        return sorted(affected)

    def _special_price(self, item, default_price) -> Decimal:
        if item.special_price_override is not None:
            return Decimal(str(item.special_price_override))
        return _round_up_5ct(
            Decimal(str(default_price.price))
            * (Decimal("100") - Decimal(str(item.discount_pct)))
            / Decimal("100")
        ).quantize(Decimal("0.01"))

    def _apply_special_price(
        self,
        *,
        prices: list,
        default_channel_id: int,
        special_price: Decimal,
    ) -> bool:
        now = timezone.now()
        special_end = _end_of_next_month(now)
        changed = False
        for price in prices:
            factor = (
                Decimal("1")
                if price.sales_channel_id == default_channel_id
                else Decimal(str(price.sales_channel.price_factor or "1"))
            )
            desired_price = _apply_channel_factor(special_price, factor)
            desired_start = price.special_start_date or now
            before = tuple(getattr(price, field) for field in self.tracked_price_fields)
            price.special_percentage = None
            price.special_price = desired_price
            price.special_start_date = desired_start
            price.special_end_date = special_end
            after = tuple(getattr(price, field) for field in self.tracked_price_fields)
            if before == after:
                continue
            price.save(history_tracked_fields=self.tracked_price_fields)
            changed = True
        return changed

    def _restore_snapshot(self, state: EmailCampaignPriceState, *, price_model) -> bool:
        snapshots = {
            int(row["price_id"]): row
            for row in state.price_snapshot or []
            if row.get("price_id") is not None
        }
        if not snapshots:
            return False
        changed = False
        for price in price_model.objects.filter(
            product_id=state.product_id,
            pk__in=snapshots,
        ):
            row = snapshots[price.pk]
            before = tuple(getattr(price, field) for field in self.tracked_price_fields)
            price.special_percentage = self._decimal_or_none(row.get("special_percentage"))
            price.special_price = self._decimal_or_none(row.get("special_price"))
            price.special_start_date = self._datetime_or_none(row.get("special_start_date"))
            price.special_end_date = self._datetime_or_none(row.get("special_end_date"))
            after = tuple(getattr(price, field) for field in self.tracked_price_fields)
            if before == after:
                continue
            price.save(history_tracked_fields=self.tracked_price_fields)
            changed = True
        return changed

    def _snapshot_prices(self, prices: list) -> list[dict[str, object]]:
        return [self._snapshot_price(price) for price in prices]

    def _extend_snapshot(self, snapshot: list, prices: list) -> list[dict[str, object]]:
        rows = list(snapshot or [])
        known_ids = {int(row["price_id"]) for row in rows if row.get("price_id") is not None}
        rows.extend(self._snapshot_price(price) for price in prices if price.pk not in known_ids)
        return rows

    def _snapshot_price(self, price) -> dict[str, object]:
        return {
            "price_id": price.pk,
            "special_percentage": self._string_or_none(price.special_percentage),
            "special_price": self._string_or_none(price.special_price),
            "special_start_date": self._iso_or_none(price.special_start_date),
            "special_end_date": self._iso_or_none(price.special_end_date),
        }

    @staticmethod
    def _string_or_none(value) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _iso_or_none(value) -> str | None:
        return None if value is None else value.isoformat()

    @staticmethod
    def _decimal_or_none(value) -> Decimal | None:
        return None if value in (None, "") else Decimal(str(value))

    @staticmethod
    def _datetime_or_none(value) -> datetime | None:
        return None if value in (None, "") else datetime.fromisoformat(str(value))


def apply_campaign_special_prices(campaign: EmailCampaign) -> list[str]:
    return EmailCampaignPriceSyncService().reconcile(campaign)


class EmailCampaignQueueService(BaseService):
    model = EmailCampaignQueueEntry

    def queue_due_campaigns_before_send(
        self,
        *,
        now=None,
        lead_time: timedelta = timedelta(days=1),
        window: timedelta = timedelta(hours=1),
    ) -> dict[str, int]:
        now = now or timezone.now()
        starts_at = now + lead_time
        ends_at = starts_at + window
        campaigns = (
            EmailCampaign.objects.filter(
                status=EmailCampaign.Status.READY,
                send_at__gte=starts_at,
                send_at__lt=ends_at,
            )
            .order_by("send_at", "pk")
        )

        summary = {
            "campaigns": 0,
            "recipients": 0,
            "queued": 0,
            "failed": 0,
        }

        for campaign in campaigns:
            summary["campaigns"] += 1
            summary_for_campaign = self.queue_campaign_recipients(campaign)
            summary["recipients"] += summary_for_campaign["recipients"]
            summary["queued"] += summary_for_campaign["queued"]
            summary["failed"] += summary_for_campaign["failed"]

        return summary

    def queue_campaign_recipients(self, campaign: EmailCampaign) -> dict[str, int]:
        from newsletter.models import NewsletterRecipient

        recipients = (
            NewsletterRecipient.objects.filter(
                selected_email_campaign=campaign,
                is_present_in_shopware=True,
                status__in=(
                    NewsletterRecipient.Status.DIRECT,
                    NewsletterRecipient.Status.OPT_IN,
                ),
            )
            .exclude(email="")
            .select_related("customer", "selected_email_campaign")
            .prefetch_related("customer__addresses")
            .order_by("pk")
        )
        summary = {
            "recipients": 0,
            "queued": 0,
            "failed": 0,
        }

        for recipient in recipients.iterator():
            summary["recipients"] += 1
            try:
                self.queue_recipient_campaign(recipient)
                summary["queued"] += 1
            except Exception:
                summary["failed"] += 1
                logger.exception(
                    "Failed to queue email campaign %s for recipient %s",
                    campaign.pk,
                    recipient.pk,
                )

        return summary

    @transaction.atomic
    def queue_recipient_campaign(self, recipient) -> EmailCampaignQueueEntry:
        campaign = recipient.selected_email_campaign

        if campaign is None:
            raise ValueError("Keine E-Mail Kampagne am Empfaenger ausgewaehlt.")
        if not recipient.email:
            raise ValueError("Empfaenger hat keine E-Mail Adresse.")
        if not recipient.is_active_status:
            raise ValueError(f"Empfaenger ist nicht aktiv (Status: {recipient.status or '-'}).")
        if not recipient.is_present_in_shopware:
            raise ValueError("Empfaenger ist nicht mehr in Shopware vorhanden.")

        mjml = render_campaign_mjml(campaign, recipient=recipient)
        html = compile_mjml_to_html(mjml)
        text = html_to_plain_text(html)

        entry = (
            self.model.objects.select_for_update()
            .filter(campaign=campaign, recipient=recipient)
            .order_by("-queued_at", "-pk")
            .first()
        )
        if entry is None:
            entry = self.model(campaign=campaign, recipient=recipient)

        entry.recipient = recipient
        entry.customer = recipient.customer
        entry.email = recipient.email
        entry.subject = campaign.internal_title
        entry.status = self.model.Status.QUEUED
        entry.rendered_mjml = mjml
        entry.rendered_html = html
        entry.rendered_text = text
        entry.error_message = ""
        entry.sent_at = None
        entry.queued_at = timezone.now()
        entry.save()
        return entry
