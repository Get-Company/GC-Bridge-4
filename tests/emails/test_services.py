from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


class TestRoundUp5ct:
    def test_rounds_up_to_nearest_5ct(self):
        from emails.services import _round_up_5ct
        assert _round_up_5ct(Decimal("9.91")) == Decimal("9.95")
        assert _round_up_5ct(Decimal("9.95")) == Decimal("9.95")
        assert _round_up_5ct(Decimal("9.96")) == Decimal("10.00")
        assert _round_up_5ct(Decimal("10.00")) == Decimal("10.00")
        assert _round_up_5ct(Decimal("10.01")) == Decimal("10.05")


class TestApplyChannelFactor:
    def test_applies_factor_and_rounds_up(self):
        from emails.services import _apply_channel_factor
        assert _apply_channel_factor(Decimal("10.00"), Decimal("1.1")) == Decimal("11.00")
        assert _apply_channel_factor(Decimal("9.10"), Decimal("1.1")) == Decimal("10.05")

    def test_returns_none_for_none_input(self):
        from emails.services import _apply_channel_factor
        assert _apply_channel_factor(None, Decimal("1.1")) is None


class TestCampaignPriceWindow:
    def test_uses_send_date_through_end_of_following_month(self):
        from emails.services import _campaign_price_window

        send_at = datetime(2026, 9, 15, 10, 30, tzinfo=UTC)
        campaign = SimpleNamespace(
            send_at=send_at,
            updated_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )
        item = SimpleNamespace(updated_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC))

        valid_from, valid_until = _campaign_price_window(campaign, item)

        assert valid_from == send_at
        assert valid_until == datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)

    def test_without_send_date_uses_latest_relevant_save(self):
        from emails.services import _campaign_price_window

        campaign = SimpleNamespace(
            send_at=None,
            updated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        )
        item = SimpleNamespace(updated_at=datetime(2026, 9, 3, 11, 15, tzinfo=UTC))

        valid_from, valid_until = _campaign_price_window(campaign, item)

        assert valid_from == item.updated_at
        assert valid_until == datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)


class TestApplyCampaignSpecialPrices:
    @pytest.mark.django_db
    def test_reconciles_removed_and_added_campaign_products(self):
        from emails.models import EmailCampaign, EmailCampaignPriceState, EmailCampaignProduct
        from emails.services import apply_campaign_special_prices
        from products.models import Price, Product
        from shopware.models import ShopwareSettings

        channel = ShopwareSettings.objects.create(name="Standard", is_default=True)
        old_product = Product.objects.create(erp_nr="581000")
        new_product = Product.objects.create(erp_nr="581001")
        old_price = Price.objects.create(
            product=old_product,
            sales_channel=channel,
            price=Decimal("100.00"),
            special_price=Decimal("90.00"),
        )
        new_price = Price.objects.create(
            product=new_product,
            sales_channel=channel,
            price=Decimal("200.00"),
        )
        send_at = datetime(2026, 9, 15, 10, 30, tzinfo=UTC)
        campaign = EmailCampaign.objects.create(
            internal_title="Produktwechsel",
            send_at=send_at,
        )
        old_item = EmailCampaignProduct.objects.create(
            campaign=campaign,
            product=old_product,
            special_price_override=Decimal("80.00"),
        )

        assert apply_campaign_special_prices(campaign) == ["581000"]
        old_price.refresh_from_db()
        assert old_price.special_price == Decimal("80.00")
        assert old_price.special_start_date == send_at
        assert old_price.special_end_date == datetime(
            2026, 10, 31, 23, 59, 59, tzinfo=UTC
        )

        old_item.delete()
        EmailCampaignProduct.objects.create(
            campaign=campaign,
            product=new_product,
            special_price_override=Decimal("150.00"),
        )

        assert apply_campaign_special_prices(campaign) == ["581000", "581001"]
        old_price.refresh_from_db()
        new_price.refresh_from_db()
        assert old_price.special_price == Decimal("90.00")
        assert new_price.special_price == Decimal("150.00")
        assert not EmailCampaignPriceState.objects.filter(product=old_product).exists()
        assert EmailCampaignPriceState.objects.get(product=new_product).campaign == campaign

    def test_snapshot_values_are_json_serializable_and_round_trip(self):
        from emails.services import EmailCampaignPriceSyncService

        service = EmailCampaignPriceSyncService()
        price = SimpleNamespace(
            pk=12,
            special_percentage=Decimal("15.00"),
            special_price=Decimal("85.00"),
            special_start_date=None,
            special_end_date=None,
        )

        snapshot = service._snapshot_price(price)

        assert snapshot == {
            "price_id": 12,
            "special_percentage": "15.00",
            "special_price": "85.00",
            "special_start_date": None,
            "special_end_date": None,
        }
        assert service._decimal_or_none(snapshot["special_price"]) == Decimal("85.00")


class TestEmailCampaignQueueService:
    @pytest.mark.django_db
    @patch("emails.services.compile_mjml_to_html", return_value="<html>neu</html>")
    @patch("emails.services.render_campaign_mjml", return_value="<mjml>neu</mjml>")
    def test_overwrites_existing_entry_for_same_campaign_and_recipient(
        self,
        render_campaign_mjml,
        compile_mjml_to_html,
    ):
        from django.utils import timezone

        from emails.models import EmailCampaign, EmailCampaignQueueEntry
        from emails.services import EmailCampaignQueueService
        from newsletter.models import NewsletterRecipient

        campaign = EmailCampaign.objects.create(
            internal_title="Sommeraktion",
            subject="Nur heute: Sommeraktion",
        )
        recipient = NewsletterRecipient.objects.create(
            shopware_id="recipient",
            email="neu@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
            selected_email_campaign=campaign,
        )
        existing_entry = EmailCampaignQueueEntry.objects.create(
            campaign=campaign,
            recipient=recipient,
            email="alt@example.com",
            subject="Alter Betreff",
            status=EmailCampaignQueueEntry.Status.FAILED,
            rendered_mjml="<mjml>alt</mjml>",
            rendered_html="<html>alt</html>",
            error_message="Fehler",
            sent_at=timezone.now(),
        )

        queued_entry = EmailCampaignQueueService().queue_recipient_campaign(recipient)

        assert queued_entry.pk == existing_entry.pk
        assert EmailCampaignQueueEntry.objects.filter(campaign=campaign, recipient=recipient).count() == 1
        assert queued_entry.recipient == recipient
        assert queued_entry.email == "neu@example.com"
        assert queued_entry.subject == "Nur heute: Sommeraktion"
        assert queued_entry.status == EmailCampaignQueueEntry.Status.QUEUED
        assert queued_entry.rendered_mjml == "<mjml>neu</mjml>"
        assert queued_entry.rendered_html == "<html>neu</html>"
        assert queued_entry.rendered_text == "neu"
        assert queued_entry.error_message == ""
        assert queued_entry.sent_at is None
        render_campaign_mjml.assert_called_once_with(campaign, recipient=recipient)
        compile_mjml_to_html.assert_called_once_with("<mjml>neu</mjml>")

    @pytest.mark.django_db
    @patch("emails.services.compile_mjml_to_html", return_value="<html>neu</html>")
    @patch("emails.services.render_campaign_mjml", return_value="<mjml>neu</mjml>")
    def test_same_customer_with_different_recipient_gets_separate_queue_entry(
        self,
        render_campaign_mjml,
        compile_mjml_to_html,
    ):
        from customer.models import Customer
        from emails.models import EmailCampaign, EmailCampaignQueueEntry
        from emails.services import EmailCampaignQueueService
        from newsletter.models import NewsletterRecipient

        campaign = EmailCampaign.objects.create(internal_title="Newsletter")
        customer = Customer.objects.create(erp_nr="10001", name="Classei")
        old_recipient = NewsletterRecipient.objects.create(
            shopware_id="recipient-old",
            customer=customer,
            is_customer=True,
            email="alt@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
            selected_email_campaign=campaign,
        )
        recipient = NewsletterRecipient.objects.create(
            shopware_id="recipient-new",
            customer=customer,
            is_customer=True,
            email="neu@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
            selected_email_campaign=campaign,
        )
        existing_entry = EmailCampaignQueueEntry.objects.create(
            campaign=campaign,
            recipient=old_recipient,
            customer=customer,
            email="alt@example.com",
            subject="Alt",
            status=EmailCampaignQueueEntry.Status.CANCELLED,
            rendered_mjml="<mjml>alt</mjml>",
            rendered_html="<html>alt</html>",
        )

        queued_entry = EmailCampaignQueueService().queue_recipient_campaign(recipient)

        assert queued_entry.pk != existing_entry.pk
        assert EmailCampaignQueueEntry.objects.filter(campaign=campaign, customer=customer).count() == 2
        assert queued_entry.recipient == recipient
        assert queued_entry.customer == customer
        assert queued_entry.email == "neu@example.com"
        assert queued_entry.status == EmailCampaignQueueEntry.Status.QUEUED
        assert queued_entry.rendered_text == "neu"
        render_campaign_mjml.assert_called_once_with(campaign, recipient=recipient)
        compile_mjml_to_html.assert_called_once_with("<mjml>neu</mjml>")

    @pytest.mark.django_db
    @patch("emails.services.compile_mjml_to_html", return_value="<html>queued</html>")
    @patch("emails.services.render_campaign_mjml", return_value="<mjml>queued</mjml>")
    def test_queue_due_campaigns_before_send_queues_ready_campaign_recipients(
        self,
        render_campaign_mjml,
        compile_mjml_to_html,
    ):
        from django.utils import timezone

        from emails.models import EmailCampaign, EmailCampaignQueueEntry
        from emails.services import EmailCampaignQueueService
        from newsletter.models import NewsletterRecipient

        now = timezone.now()
        due_campaign = EmailCampaign.objects.create(
            internal_title="Faellige Kampagne",
            status=EmailCampaign.Status.READY,
            send_at=now + timedelta(days=1, minutes=30),
        )
        EmailCampaign.objects.create(
            internal_title="Entwurf",
            status=EmailCampaign.Status.DRAFT,
            send_at=now + timedelta(days=1, minutes=30),
        )
        EmailCampaign.objects.create(
            internal_title="Spaeter",
            status=EmailCampaign.Status.READY,
            send_at=now + timedelta(days=1, hours=2),
        )
        active_recipient = NewsletterRecipient.objects.create(
            shopware_id="active-due",
            email="active@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
            selected_email_campaign=due_campaign,
        )
        NewsletterRecipient.objects.create(
            shopware_id="inactive-due",
            email="inactive@example.com",
            status=NewsletterRecipient.Status.OPT_OUT,
            selected_email_campaign=due_campaign,
        )
        NewsletterRecipient.objects.create(
            shopware_id="missing-due",
            email="missing@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
            is_present_in_shopware=False,
            selected_email_campaign=due_campaign,
        )

        summary = EmailCampaignQueueService().queue_due_campaigns_before_send(now=now)

        assert summary == {
            "campaigns": 1,
            "recipients": 1,
            "queued": 1,
            "failed": 0,
        }
        entry = EmailCampaignQueueEntry.objects.get()
        assert entry.campaign == due_campaign
        assert entry.recipient == active_recipient
        assert entry.rendered_mjml == "<mjml>queued</mjml>"
        assert entry.rendered_html == "<html>queued</html>"
        assert entry.rendered_text == "queued"
        render_campaign_mjml.assert_called_once_with(due_campaign, recipient=active_recipient)
        compile_mjml_to_html.assert_called_once_with("<mjml>queued</mjml>")

    @pytest.mark.django_db
    def test_rejects_recipient_missing_from_shopware(self):
        from emails.models import EmailCampaign
        from emails.services import EmailCampaignQueueService
        from newsletter.models import NewsletterRecipient

        campaign = EmailCampaign.objects.create(internal_title="Newsletter")
        recipient = NewsletterRecipient.objects.create(
            shopware_id="missing-recipient",
            email="missing@example.com",
            status=NewsletterRecipient.Status.OPT_IN,
            is_present_in_shopware=False,
            selected_email_campaign=campaign,
        )

        with pytest.raises(ValueError, match="nicht mehr in Shopware"):
            EmailCampaignQueueService().queue_recipient_campaign(recipient)
