from __future__ import annotations

import calendar
import hashlib
import logging
import uuid
from email.utils import formataddr
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_UP

from django.core.mail import EmailMultiAlternatives, get_connection
from django.conf import settings
from django.db import transaction
from django.db.models import Q
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


def _end_of_next_month(anchor: datetime) -> datetime:
    next_month = (anchor.month % 12) + 1
    year = anchor.year + (1 if next_month == 1 else 0)
    last_day = calendar.monthrange(year, next_month)[1]
    return anchor.replace(
        year=year, month=next_month, day=last_day,
        hour=23, minute=59, second=59, microsecond=0,
    )


def _campaign_price_window(campaign: EmailCampaign, item) -> tuple[datetime, datetime]:
    valid_from = campaign.send_at or max(campaign.updated_at, item.updated_at)
    return valid_from, _end_of_next_month(valid_from)


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
                valid_from, valid_until = _campaign_price_window(campaign, item)
                changed = self._apply_special_price(
                    prices=prices,
                    default_channel_id=default_channel.pk,
                    special_price=special_price,
                    valid_from=valid_from,
                    valid_until=valid_until,
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
        valid_from: datetime,
        valid_until: datetime,
    ) -> bool:
        changed = False
        for price in prices:
            factor = (
                Decimal("1")
                if price.sales_channel_id == default_channel_id
                else Decimal(str(price.sales_channel.price_factor or "1"))
            )
            desired_price = _apply_channel_factor(special_price, factor)
            before = tuple(getattr(price, field) for field in self.tracked_price_fields)
            price.special_percentage = None
            price.special_price = desired_price
            price.special_start_date = valid_from
            price.special_end_date = valid_until
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
        # Keep window for task API compatibility. Repeated runs catch campaigns
        # scheduled less than a day ahead, while get_or_create keeps one entry.
        starts_at = now + lead_time
        campaigns = (
            EmailCampaign.objects.filter(
                pk=settings.NEWSLETTER_SERIES_CAMPAIGN_ID,
                status=EmailCampaign.Status.READY,
                # A delayed Beat run may catch up for one hour. Older sends
                # require an operator decision instead of a surprise mailing.
                send_at__gte=now - timedelta(hours=1),
                send_at__lte=starts_at,
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

        for recipient in recipients.iterator(chunk_size=100):
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

        # Never reset a sent, in-flight, cancelled or ambiguous failed delivery.
        existing = self.model.objects.filter(
            campaign=campaign, recipient=recipient, test_batch__isnull=True
        ).first()
        if existing is not None:
            return existing

        mjml = render_campaign_mjml(campaign, recipient=recipient)
        html = compile_mjml_to_html(mjml)
        text = html_to_plain_text(html)

        entry, _ = self.model.objects.get_or_create(
            campaign=campaign,
            recipient=recipient,
            test_batch=None,
            defaults={
                "customer": recipient.customer,
                "email": recipient.email,
                "subject": campaign.subject.strip() or campaign.internal_title,
                "rendered_mjml": mjml,
                "rendered_html": html,
                "rendered_text": text,
            },
        )
        return entry


class EmailCampaignTestQueueService(BaseService):
    """Queue marked contacts through the ordinary newsletter worker."""

    model = EmailCampaignQueueEntry
    max_recipients = 20

    @staticmethod
    def selection_fingerprint(campaign: EmailCampaign) -> str:
        from newsletter.models import NewsletterRecipient

        rows = list(
            NewsletterRecipient.objects.filter(is_test_recipient=True)
            .order_by("pk")
            .values_list("pk", "email", "status", "is_present_in_shopware")
        )
        selection = (
            campaign.pk, campaign.updated_at.isoformat(), campaign.status,
            campaign.subject, rows,
        )
        return hashlib.sha256(repr(selection).encode("utf-8")).hexdigest()

    def queue_marked(self, *, campaign: EmailCampaign, expected_fingerprint: str) -> dict[str, int]:
        from newsletter.models import NewsletterRecipient

        if campaign.status != EmailCampaign.Status.DRAFT:
            raise ValueError("Testversand ist nur für Entwürfe möglich.")
        if expected_fingerprint != self.selection_fingerprint(campaign):
            raise ValueError("Die Testempfänger oder Kampagne haben sich geändert. Bitte erneut bestätigen.")

        recipients = list(
            NewsletterRecipient.objects.filter(is_test_recipient=True)
            .order_by("pk")[: self.max_recipients + 1]
        )
        if not recipients:
            raise ValueError("Es sind keine Testempfänger markiert.")
        if len(recipients) > self.max_recipients:
            raise ValueError(f"Höchstens {self.max_recipients} Testempfänger sind erlaubt.")

        smtp = EmailSmtpSettings.objects.filter(pk=1).first()
        if smtp is None:
            raise EmailSmtpSettingsError("Keine SMTP-Konfiguration vorhanden.")
        EmailSmtpSettingsService.build_connection(smtp)

        batch = uuid.uuid4()
        summary = {"queued": 0, "skipped": 0, "failed": 0}
        seen_emails = set()
        for recipient in recipients:
            email = recipient.email.strip()
            key = email.casefold()
            if (
                not email or key in seen_emails or not recipient.is_present_in_shopware
                or not recipient.is_active_status
            ):
                summary["skipped"] += 1
                continue
            seen_emails.add(key)
            try:
                mjml = render_campaign_mjml(campaign, recipient=recipient)
                html = compile_mjml_to_html(mjml)
                self.model.objects.create(
                    campaign=campaign,
                    recipient=recipient,
                    test_batch=batch,
                    customer=recipient.customer,
                    email=email,
                    subject=f"[Test] {campaign.subject.strip() or campaign.internal_title}",
                    rendered_mjml=mjml,
                    rendered_html=html,
                    rendered_text=html_to_plain_text(html),
                )
                summary["queued"] += 1
            except Exception:
                summary["failed"] += 1
                logger.exception("Failed to queue test campaign %s for recipient %s", campaign.pk, recipient.pk)
        return summary


class EmailCampaignSendService(BaseService):
    """Deliver a small, rate-limited batch while rechecking Shopware consent."""

    model = EmailCampaignQueueEntry
    max_attempts = 5

    def send_due_entries(self, *, now=None, batch_size: int = 10) -> dict[str, int]:
        from newsletter.services.recipient_sync import NewsletterRecipientShopwareService

        now = now or timezone.now()
        summary = {"sent": 0, "cancelled": 0, "retry": 0, "failed": 0, "disabled": 0, "stale_sending": 0}
        summary["stale_sending"] = self.model.objects.filter(
            status=self.model.Status.SENDING,
            last_attempt_at__lt=now - timedelta(minutes=10),
        ).count()
        if summary["stale_sending"]:
            logger.error("Newsletter queue has %s stale SENDING entries needing manual review", summary["stale_sending"])
        smtp = EmailSmtpSettings.objects.filter(pk=1).first()
        if smtp is None or not smtp.smtp_is_configured:
            summary["disabled"] = 1
            return summary
        if not self.model.objects.filter(
            status=self.model.Status.QUEUED,
            test_batch__isnull=False,
        ).exists() and (
            not settings.NEWSLETTER_SERIES_SEND_ENABLED
            or not settings.NEWSLETTER_SERIES_CAMPAIGN_ID
            or not smtp.is_active
        ):
            summary["disabled"] = 1
            return summary

        allowance = max(0, min(int(batch_size), 10))
        shopware = NewsletterRecipientShopwareService()
        for _ in range(allowance):
            entry_id = self._claim_one(timezone.now(), allowance)
            if entry_id is None:
                break
            outcome = self._send_claimed(entry_id, smtp=smtp, shopware=shopware)
            summary[outcome] += 1
        return summary

    @transaction.atomic
    def _claim_one(self, now, batch_size: int) -> int | None:
        # Serialize slot reservations across workers/manual task invocations.
        # Count all attempts, including uncertain SMTP outcomes, conservatively.
        if not EmailSmtpSettings.objects.select_for_update().filter(pk=1).exists():
            return None
        recent_attempts = self.model.objects.filter(
            last_attempt_at__gte=now - timedelta(minutes=1),
        ).count()
        if recent_attempts >= batch_size:
            return None
        eligible = Q(
            test_batch__isnull=False,
        )
        if (
            settings.NEWSLETTER_SERIES_SEND_ENABLED
            and settings.NEWSLETTER_SERIES_CAMPAIGN_ID
            and EmailSmtpSettings.objects.filter(pk=1, is_active=True).exists()
        ):
            eligible |= Q(
                test_batch__isnull=True,
                campaign_id=settings.NEWSLETTER_SERIES_CAMPAIGN_ID,
                campaign__status=EmailCampaign.Status.READY,
                campaign__send_at__lte=now,
            )
        entry = (
            self.model.objects.select_for_update(skip_locked=True)
            .filter(status=self.model.Status.QUEUED)
            .filter(eligible)
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by("queued_at", "pk")
            .first()
        )
        if entry is None:
            return None
        entry.status = self.model.Status.SENDING
        entry.attempt_count += 1
        entry.last_attempt_at = now
        entry.save(update_fields=("status", "attempt_count", "last_attempt_at", "updated_at"))
        return entry.pk

    def _send_claimed(self, entry_id: int, *, smtp: EmailSmtpSettings, shopware) -> str:
        from newsletter.models import NewsletterRecipient
        from newsletter.services.recipient_sync import _normalize_entity
        from newsletter.links import unsubscribe_url

        entry = self.model.objects.select_related("campaign", "recipient").get(pk=entry_id)
        recipient = entry.recipient
        campaign = entry.campaign
        is_test = entry.test_batch is not None
        if is_test and campaign.status != EmailCampaign.Status.DRAFT:
            self._finish(entry_id, self.model.Status.CANCELLED, "Testkampagne ist kein Entwurf mehr.")
            return "cancelled"
        campaign_ready = (
            campaign.status == EmailCampaign.Status.DRAFT
            if is_test else (
                settings.NEWSLETTER_SERIES_SEND_ENABLED
                and campaign.pk == settings.NEWSLETTER_SERIES_CAMPAIGN_ID
                and smtp.is_active
                and campaign.status == EmailCampaign.Status.READY
                and campaign.send_at is not None
                and campaign.send_at <= timezone.now()
            )
        )
        if not campaign_ready:
            self._finish(entry_id, self.model.Status.QUEUED, "Kampagne nicht versandbereit.")
            return "retry"
        if is_test and (
            not recipient.is_test_recipient
        ):
            self._finish(entry_id, self.model.Status.CANCELLED, "Empfänger nicht mehr als Testempfänger markiert.")
            return "cancelled"
        if (
            not recipient.is_present_in_shopware
            or not recipient.is_active_status
            or (not is_test and recipient.selected_email_campaign_id != campaign.pk)
            or recipient.email.casefold() != entry.email.casefold()
        ):
            self._finish(entry_id, self.model.Status.CANCELLED, "Empfänger lokal nicht mehr aktiv oder geändert.")
            return "cancelled"
        if self.model.objects.filter(
            **({"test_batch": entry.test_batch} if is_test else {"campaign": campaign, "test_batch__isnull": True}),
            email__iexact=entry.email,
            status__in=(self.model.Status.SENDING, self.model.Status.SENT, self.model.Status.FAILED),
        ).exclude(pk=entry.pk).exists():
            self._finish(entry_id, self.model.Status.CANCELLED, "E-Mail-Adresse in dieser Kampagne bereits verarbeitet.")
            return "cancelled"

        try:
            response = shopware.request_post(
                "/search/newsletter-recipient",
                payload={"page": 1, "limit": 1, "filter": [
                    {"type": "equals", "field": "id", "value": recipient.shopware_id},
                ]},
            )
            rows = (response or {}).get("data") or []
            remote = _normalize_entity(rows[0]) if rows else None
        except Exception as exc:
            return self._retry_before_smtp(entry, exc)
        if remote is None or str(remote.get("id", "")) != recipient.shopware_id:
            self._finish(entry_id, self.model.Status.CANCELLED, "Empfänger in Shopware nicht gefunden.")
            return "cancelled"
        if (
            str(remote.get("status", "")) not in (NewsletterRecipient.Status.DIRECT, NewsletterRecipient.Status.OPT_IN)
            or str(remote.get("email", "")).casefold() != entry.email.casefold()
        ):
            self._finish(entry_id, self.model.Status.CANCELLED, "Empfänger in Shopware abgemeldet oder geändert.")
            return "cancelled"

        # The operator can pause a campaign or disable SMTP while a batch runs.
        current = self.model.objects.select_related("campaign", "recipient").get(pk=entry_id)
        if (
            (current.campaign.status != EmailCampaign.Status.DRAFT if is_test else (
                not settings.NEWSLETTER_SERIES_SEND_ENABLED
                or current.campaign_id != settings.NEWSLETTER_SERIES_CAMPAIGN_ID
                or current.campaign.status != EmailCampaign.Status.READY
                or current.campaign.send_at is None
                or current.campaign.send_at > timezone.now()
            ))
            or not current.recipient.is_active_status
            or not current.recipient.is_present_in_shopware
            or current.recipient.email.casefold() != entry.email.casefold()
            or (is_test and not current.recipient.is_test_recipient)
        ):
            self._finish(entry_id, self.model.Status.CANCELLED, "Empfänger oder Kampagne vor SMTP geändert.")
            return "cancelled"
        if not is_test and not EmailSmtpSettings.objects.filter(pk=smtp.pk, is_active=True).exists():
            self._finish(entry_id, self.model.Status.QUEUED, "SMTP wurde deaktiviert.", retry_at=timezone.now() + timedelta(minutes=1))
            return "retry"

        # QUEUED is a preview snapshot. Render again for the current campaign
        # and recipient immediately before delivery, so edits made during the
        # lead time cannot silently send stale content.
        try:
            entry.rendered_mjml = render_campaign_mjml(current.campaign, recipient=current.recipient)
            entry.rendered_html = compile_mjml_to_html(entry.rendered_mjml)
            entry.rendered_text = html_to_plain_text(entry.rendered_html)
            entry.subject = (
                f"[Test] {current.campaign.subject.strip() or current.campaign.internal_title}"
                if is_test else current.campaign.subject.strip() or current.campaign.internal_title
            )
            entry.save(update_fields=("rendered_mjml", "rendered_html", "rendered_text", "subject", "updated_at"))
        except Exception as exc:
            return self._retry_before_smtp(entry, exc)

        try:
            connection = EmailSmtpSettingsService.build_connection(smtp)
            connection.open()
        except Exception as exc:
            return self._retry_before_smtp(entry, exc)

        try:
            # Recheck after connection.open(), which can itself take seconds.
            try:
                latest_response = shopware.request_post(
                    "/search/newsletter-recipient",
                    payload={"page": 1, "limit": 1, "filter": [
                        {"type": "equals", "field": "id", "value": recipient.shopware_id},
                    ]},
                )
                latest_rows = (latest_response or {}).get("data") or []
                latest_remote = _normalize_entity(latest_rows[0]) if latest_rows else None
            except Exception as exc:
                return self._retry_before_smtp(entry, exc)
            if (
                latest_remote is None
                or str(latest_remote.get("id", "")) != recipient.shopware_id
                or str(latest_remote.get("status", "")) not in (NewsletterRecipient.Status.DIRECT, NewsletterRecipient.Status.OPT_IN)
                or str(latest_remote.get("email", "")).casefold() != entry.email.casefold()
            ):
                self._finish(entry_id, self.model.Status.CANCELLED, "Empfänger vor SMTP in Shopware abgemeldet oder geändert.")
                return "cancelled"
            latest_entry = self.model.objects.select_related("campaign", "recipient").get(pk=entry_id)
            if is_test and (
                latest_entry.campaign.status != EmailCampaign.Status.DRAFT
                or not latest_entry.recipient.is_test_recipient
                or not latest_entry.recipient.is_active_status
                or not latest_entry.recipient.is_present_in_shopware
                or latest_entry.recipient.email.casefold() != entry.email.casefold()
            ):
                self._finish(entry_id, self.model.Status.CANCELLED, "Testmarkierung oder Empfänger vor SMTP geändert.")
                return "cancelled"
            try:
                message = EmailMultiAlternatives(
                    subject=entry.subject,
                    body=entry.rendered_text,
                    from_email=formataddr((smtp.sender_name, smtp.sender_email)),
                    to=[entry.email],
                    reply_to=[smtp.effective_reply_to_email],
                    headers={"List-Unsubscribe": f"<{unsubscribe_url(entry.email)}>"},
                    connection=connection,
                )
                message.attach_alternative(entry.rendered_html, "text/html")
                accepted = message.send(fail_silently=False)
            except Exception as exc:
                # An SMTP exception after DATA may mean accepted-but-unacknowledged.
                # Such entries require inspection rather than an automatic duplicate.
                self._finish(entry_id, self.model.Status.FAILED, f"SMTP-Ergebnis unklar: {type(exc).__name__}: {exc}")
                return "failed"
        finally:
            try:
                connection.close()
            except Exception:
                logger.warning("Closing SMTP connection failed", exc_info=True)
        if accepted != 1:
            self._finish(entry_id, self.model.Status.FAILED, "SMTP hat keine Zustellung bestätigt.")
            return "failed"
        self._finish(entry_id, self.model.Status.SENT, "")
        return "sent"

    def _retry_before_smtp(self, entry: EmailCampaignQueueEntry, exc: Exception) -> str:
        if entry.attempt_count >= self.max_attempts:
            self._finish(entry.pk, self.model.Status.FAILED, f"Vor Versand fehlgeschlagen: {type(exc).__name__}: {exc}")
            return "failed"
        delay = timedelta(minutes=min(2 ** entry.attempt_count, 30))
        self._finish(entry.pk, self.model.Status.QUEUED, f"Vor Versand fehlgeschlagen: {type(exc).__name__}: {exc}", retry_at=timezone.now() + delay)
        return "retry"

    def _finish(self, entry_id: int, status: str, error: str, *, retry_at=None) -> None:
        changes = {
            "status": status,
            "error_message": error[:1000],
            "next_attempt_at": retry_at,
        }
        if status == self.model.Status.SENT:
            changes["sent_at"] = timezone.now()
        self.model.objects.filter(pk=entry_id, status=self.model.Status.SENDING).update(**changes)
