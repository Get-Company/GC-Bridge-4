from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from celery import shared_task
from django.core.management import call_command
from django.db.models import Prefetch, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="emails.apply_campaign_prices_async")
def apply_campaign_prices_async(campaign_pk: int) -> None:
    from emails.models import EmailCampaign
    from emails.services import apply_campaign_special_prices
    from products.tasks import microtech_update_prices, shopware_sync_products

    try:
        campaign = EmailCampaign.objects.get(pk=campaign_pk)
    except EmailCampaign.DoesNotExist:
        return

    erp_nrs = apply_campaign_special_prices(campaign)
    if erp_nrs:
        microtech_update_prices.delay(erp_nrs)
        shopware_sync_products.delay(erp_nrs, skip_images=True)


def _shopware_activation_fingerprint(campaign, items, *, phase: str) -> str:
    payload = {
        "campaign": campaign.pk,
        "send_at": campaign.send_at.isoformat(),
        "phase": phase,
        "products": [
            {
                "id": item.pk,
                "erp_nr": item.product.erp_nr,
                "special_price": str(item.special_price_override or ""),
                "discount_pct": str(item.discount_pct or ""),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in items
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@shared_task(name="emails.sync_due_campaign_prices_to_shopware")
def sync_due_campaign_prices_to_shopware() -> dict[str, int]:
    """Publish campaign specials when their validity starts and clear them after expiry."""
    from emails.models import EmailCampaign, EmailCampaignProduct
    from emails.services import _end_of_next_month, apply_campaign_special_prices
    from products.tasks import microtech_update_prices

    now = timezone.now()
    campaign_products = EmailCampaignProduct.objects.filter(
        Q(special_price_override__isnull=False) | Q(discount_pct__isnull=False)
    ).select_related("product")
    campaigns = list(
        EmailCampaign.objects.filter(
            send_at__isnull=False,
            send_at__lte=now,
        )
        .prefetch_related(
            Prefetch(
                "campaign_products",
                queryset=campaign_products,
                to_attr="discount_products",
            )
        )
        .order_by("send_at", "pk")
    )
    summary = {
        "campaigns": len(campaigns),
        "activated": 0,
        "expired": 0,
        "skipped": 0,
        "failed": 0,
    }

    for campaign in campaigns:
        items = sorted(campaign.discount_products, key=lambda item: item.pk)
        if not items:
            summary["skipped"] += 1
            continue

        phase = "active" if now <= _end_of_next_month(campaign.send_at) else "expired"
        if phase == "active" and campaign.status != EmailCampaign.Status.READY:
            summary["skipped"] += 1
            continue
        fingerprint = _shopware_activation_fingerprint(campaign, items, phase=phase)
        if campaign.shopware_price_activation_fingerprint == fingerprint:
            summary["skipped"] += 1
            continue

        erp_nrs = sorted({item.product.erp_nr for item in items if item.product.erp_nr})
        if not erp_nrs:
            summary["skipped"] += 1
            continue

        try:
            microtech_changes = apply_campaign_special_prices(campaign)
            if microtech_changes:
                microtech_update_prices.delay(microtech_changes)
            call_command("shopware_sync_products", *erp_nrs, skip_images=True)
        except Exception:
            summary["failed"] += 1
            logger.exception(
                "Timed Shopware campaign price sync failed for campaign %s (%s)",
                campaign.pk,
                phase,
            )
            continue

        update_filter = EmailCampaign.objects.filter(
            pk=campaign.pk,
            send_at=campaign.send_at,
        )
        if phase == "active":
            update_filter = update_filter.filter(status=EmailCampaign.Status.READY)
        updated = update_filter.update(
            shopware_price_activation_fingerprint=fingerprint,
            shopware_prices_activated_at=now,
        )
        if updated:
            summary["activated" if phase == "active" else "expired"] += 1

    return summary


@shared_task(name="emails.queue_due_campaigns_before_send")
def queue_due_campaigns_before_send(
    lead_time_hours: int = 24,
    window_minutes: int = 60,
) -> dict[str, int]:
    from emails.services import EmailCampaignQueueService

    return EmailCampaignQueueService().queue_due_campaigns_before_send(
        lead_time=timedelta(hours=lead_time_hours),
        window=timedelta(minutes=window_minutes),
    )
