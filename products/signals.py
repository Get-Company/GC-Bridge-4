from __future__ import annotations

from decimal import Decimal

from django.dispatch import Signal, receiver

from products.models import Price, PriceIncrease
from shopware.models import ShopwareSettings

price_increase_applied = Signal()

MIN_PRICE_FACTOR = Decimal("0.01")
MAX_PRICE_FACTOR = Decimal("10.00")


def _normalize_price_factor(value) -> Decimal:
    if value in (None, ""):
        return Decimal("1.0")
    try:
        factor = Decimal(str(value))
    except Exception:
        return Decimal("1.0")
    if factor < MIN_PRICE_FACTOR or factor > MAX_PRICE_FACTOR:
        return Decimal("1.0")
    return factor


def _apply_factor(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    return Price._round_up_5ct(Decimal(value) * factor).quantize(Decimal("0.01"))


@receiver(price_increase_applied)
def sync_price_increase_to_other_sales_channels(sender, *, price_increase_id: int, updated_price_ids: list[int], **kwargs):
    price_increase = (
        PriceIncrease.objects.select_related("sales_channel")
        .filter(pk=price_increase_id)
        .first()
    )
    if not price_increase or not price_increase.sales_channel_id or not updated_price_ids:
        return

    default_prices = list(
        Price.objects.select_related("product")
        .filter(pk__in=updated_price_ids, sales_channel_id=price_increase.sales_channel_id)
    )
    if not default_prices:
        return

    other_channels = list(
        ShopwareSettings.objects.filter(is_active=True)
        .exclude(pk=price_increase.sales_channel_id)
        .order_by("pk")
    )
    for base_price in default_prices:
        for channel in other_channels:
            factor = _normalize_price_factor(channel.price_factor)
            Price.objects.update_or_create(
                product=base_price.product,
                sales_channel=channel,
                defaults={
                    "price": _apply_factor(base_price.price, factor),
                    "rebate_quantity": base_price.rebate_quantity,
                    "rebate_price": _apply_factor(base_price.rebate_price, factor),
                    "special_percentage": base_price.special_percentage,
                    "special_price": _apply_factor(base_price.special_price, factor),
                    "special_start_date": base_price.special_start_date,
                    "special_end_date": base_price.special_end_date,
                },
            )
