from __future__ import annotations

import calendar
from decimal import Decimal, ROUND_UP

from django.utils import timezone

from products.models import Price
from shopware.models import ShopwareSettings


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
    """Writes special_price back to ProductPrice entries for campaign component products.

    Uses the default sales channel as base price source. Propagates to all
    other active channels using their price_factor (rounded up to 5ct).

    Returns list of erp_nrs updated (used to trigger Microtech + Shopware sync).
    """
    default_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
    if not default_channel:
        return []

    other_channels = list(
        ShopwareSettings.objects.filter(is_active=True).exclude(pk=default_channel.pk)
    )

    now = timezone.now()
    special_end = _end_of_next_month(now)
    affected_erp_nrs: list[str] = []

    components = campaign.components.select_related("product", "campaign_product__product").all()
    for component in components:
        product = getattr(component, "product", None)
        special_price_override = getattr(component, "special_price_override", None)
        discount_pct = getattr(component, "discount_pct", None)
        legacy_campaign_product = getattr(component, "campaign_product", None)
        if product is None and legacy_campaign_product is not None:
            product = legacy_campaign_product.product
            special_price_override = legacy_campaign_product.special_price_override
            discount_pct = legacy_campaign_product.discount_pct

        if product is None or (not special_price_override and not discount_pct):
            continue

        default_price = Price.objects.filter(
            product=product, sales_channel=default_channel
        ).first()
        if not default_price:
            continue

        if special_price_override:
            special_price = Decimal(str(special_price_override))
        else:
            base = Decimal(str(default_price.price))
            special_price = _round_up_5ct(
                base * (Decimal("100") - Decimal(str(discount_pct))) / Decimal("100")
            )

        default_price.special_price = special_price
        if not default_price.special_start_date:
            default_price.special_start_date = now
        default_price.special_end_date = special_end
        default_price.save(
            history_tracked_fields=["special_price", "special_start_date", "special_end_date"]
        )

        for channel in other_channels:
            factor_val = channel.price_factor
            factor = Decimal(str(factor_val)) if factor_val else Decimal("1.0")
            channel_price = Price.objects.filter(product=product, sales_channel=channel).first()
            if channel_price:
                channel_price.special_price = _apply_channel_factor(special_price, factor)
                if not channel_price.special_start_date:
                    channel_price.special_start_date = now
                channel_price.special_end_date = special_end
                channel_price.save(
                    history_tracked_fields=["special_price", "special_start_date", "special_end_date"]
                )

        component.prices_synced_at = now
        component.save(update_fields=["prices_synced_at"])
        if legacy_campaign_product is not None and getattr(component, "product", None) is None:
            legacy_campaign_product.prices_synced_at = now
            legacy_campaign_product.save(update_fields=["prices_synced_at"])
        affected_erp_nrs.append(product.erp_nr)

    return affected_erp_nrs
