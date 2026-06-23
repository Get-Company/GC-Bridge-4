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
    def test_returns_empty_without_writing_product_prices(self):
        from emails.services import apply_campaign_special_prices
        campaign = MagicMock()

        result = apply_campaign_special_prices(campaign)

        assert result == []

    def test_does_not_touch_campaign_relations(self):
        from emails.services import apply_campaign_special_prices
        campaign = MagicMock()

        result = apply_campaign_special_prices(campaign)

        assert result == []
        campaign.components.select_related.assert_not_called()
