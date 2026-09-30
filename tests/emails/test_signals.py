from unittest.mock import patch


@patch("emails.signals.transaction.on_commit", side_effect=lambda callback: callback())
@patch("emails.tasks.apply_campaign_prices_async.delay")
def test_campaign_product_delete_enqueues_campaign_reconciliation(delay, on_commit):
    from emails.signals import sync_campaign_prices_after_product_delete

    instance = type("CampaignProduct", (), {"campaign_id": 3})()

    sync_campaign_prices_after_product_delete(sender=object(), instance=instance)

    on_commit.assert_called_once()
    delay.assert_called_once_with(3)
