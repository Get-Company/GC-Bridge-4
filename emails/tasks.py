from __future__ import annotations

from datetime import timedelta

from celery import shared_task


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
        shopware_sync_products.delay(erp_nrs)


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
