from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from emails.models import EmailCampaign, EmailCampaignProduct


def _enqueue_campaign_price_sync(campaign_id: int) -> None:
    from emails.tasks import apply_campaign_prices_async

    transaction.on_commit(lambda: apply_campaign_prices_async.delay(campaign_id))


def _enqueue_external_price_sync(erp_nrs: list[str]) -> None:
    if not erp_nrs:
        return

    def enqueue() -> None:
        from products.tasks import microtech_update_prices, shopware_sync_products

        microtech_update_prices.delay(erp_nrs)
        shopware_sync_products.delay(erp_nrs, skip_images=True)

    transaction.on_commit(enqueue)


@receiver(
    post_save,
    sender=EmailCampaign,
    dispatch_uid="emails_sync_campaign_prices_after_save",
)
def sync_campaign_prices_after_save(
    sender,
    instance: EmailCampaign,
    raw: bool = False,
    **kwargs,
) -> None:
    if not raw:
        _enqueue_campaign_price_sync(instance.pk)


@receiver(
    post_save,
    sender=EmailCampaignProduct,
    dispatch_uid="emails_sync_campaign_prices_after_product_save",
)
def sync_campaign_prices_after_product_save(
    sender,
    instance: EmailCampaignProduct,
    raw: bool = False,
    **kwargs,
) -> None:
    if not raw:
        _enqueue_campaign_price_sync(instance.campaign_id)


@receiver(
    post_delete,
    sender=EmailCampaignProduct,
    dispatch_uid="emails_sync_campaign_prices_after_product_delete",
)
def sync_campaign_prices_after_product_delete(
    sender,
    instance: EmailCampaignProduct,
    **kwargs,
) -> None:
    _enqueue_campaign_price_sync(instance.campaign_id)


@receiver(
    pre_delete,
    sender=EmailCampaign,
    dispatch_uid="emails_restore_campaign_prices_before_delete",
)
def restore_campaign_prices_before_delete(sender, instance: EmailCampaign, **kwargs) -> None:
    from emails.services import EmailCampaignPriceSyncService

    _enqueue_external_price_sync(EmailCampaignPriceSyncService().release(instance))
