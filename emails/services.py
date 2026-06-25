from __future__ import annotations

import calendar
from decimal import Decimal, ROUND_UP

from django.db import transaction
from django.utils import timezone

from core.services import BaseService
from emails.mjml import compile_mjml_to_html, render_campaign_mjml
from emails.models import EmailCampaignQueueEntry


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


def apply_campaign_special_prices(campaign) -> list[str]:
    """Campaigns no longer write product prices.

    Special prices are maintained directly on Product Price entries and read
    during rendering through ProductEmailProxy.
    """
    return []


class EmailCampaignQueueService(BaseService):
    model = EmailCampaignQueueEntry

    @transaction.atomic
    def queue_recipient_campaign(self, recipient) -> EmailCampaignQueueEntry:
        campaign = recipient.selected_email_campaign

        if campaign is None:
            raise ValueError("Keine E-Mail Kampagne am Empfaenger ausgewaehlt.")
        if not recipient.email:
            raise ValueError("Empfaenger hat keine E-Mail Adresse.")
        if not recipient.is_active_status:
            raise ValueError(f"Empfaenger ist nicht aktiv (Status: {recipient.status or '-'}).")

        mjml = render_campaign_mjml(campaign, recipient=recipient)
        html = compile_mjml_to_html(mjml)

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
        entry.error_message = ""
        entry.sent_at = None
        entry.queued_at = timezone.now()
        entry.save()
        return entry
