from __future__ import annotations

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
