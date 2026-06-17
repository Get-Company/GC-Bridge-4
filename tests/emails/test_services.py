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


class TestApplyCampaignSpecialPrices:
    @patch("emails.services.ShopwareSettings")
    def test_returns_empty_when_no_default_channel(self, MockSettings):
        from emails.services import apply_campaign_special_prices
        MockSettings.objects.filter.return_value.first.return_value = None
        campaign = MagicMock()
        result = apply_campaign_special_prices(campaign)
        assert result == []

    @patch("emails.services.ShopwareSettings")
    @patch("emails.services.Price")
    def test_skips_products_without_price_fields(self, MockPrice, MockSettings):
        from emails.services import apply_campaign_special_prices
        default_ch = SimpleNamespace(pk=1, price_factor=Decimal("1.0"), is_active=True)
        MockSettings.objects.filter.return_value.first.return_value = default_ch
        MockSettings.objects.filter.return_value.exclude.return_value = []

        cp = MagicMock()
        cp.special_price_override = None
        cp.discount_pct = None
        campaign = MagicMock()
        campaign.campaign_products.select_related.return_value.all.return_value = [cp]

        result = apply_campaign_special_prices(campaign)
        assert result == []
        MockPrice.objects.filter.assert_not_called()
