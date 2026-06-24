from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import Signal, receiver

from products.models import Price, PriceIncrease, Product, Storage
from products.services import ProductAutoSyncService, is_product_auto_sync_disabled
from shopware.models import ShopwareSettings

price_increase_applied = Signal()

MIN_PRICE_FACTOR = Decimal("0.01")
MAX_PRICE_FACTOR = Decimal("10.00")
PRODUCT_AUTO_SYNC_FIELDS = (
    "erp_nr",
    "gtin",
    "name",
    "sort_order",
    "description",
    "description_short",
    "is_active",
    "factor",
    "unit",
    "min_purchase",
    "purchase_unit",
    "customs_tariff_number",
    "weight_gross",
    "weight_net",
    "tax_id",
)
PRICE_AUTO_SYNC_FIELDS = (
    "sales_channel_id",
    "price",
    "rebate_quantity",
    "rebate_price",
    "special_percentage",
    "special_price",
    "special_start_date",
    "special_end_date",
)
STORAGE_AUTO_SYNC_FIELDS = (
    "stock",
    "virtual_stock",
    "location",
)


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


def _enqueue_product_sync_on_commit(*, product_id: int | None, changed_fields: list[str], trigger: str) -> None:
    if not product_id or not changed_fields:
        return

    def enqueue_after_commit() -> None:
        ProductAutoSyncService().enqueue_product_sync(
            product_id=product_id,
            changed_fields=changed_fields,
            trigger=trigger,
        )

    transaction.on_commit(enqueue_after_commit)


@receiver(pre_save, sender=Product, dispatch_uid="products_capture_product_auto_sync_changes")
def capture_product_auto_sync_changes(sender, instance: Product, raw: bool = False, update_fields=None, **kwargs):
    if raw or is_product_auto_sync_disabled():
        instance._auto_sync_changed_fields = []
        return

    watched_fields = set(PRODUCT_AUTO_SYNC_FIELDS)
    if update_fields is not None:
        watched_fields &= {str(field) for field in update_fields}
        if not watched_fields:
            instance._auto_sync_changed_fields = []
            return

    if not instance.pk:
        instance._auto_sync_changed_fields = sorted(watched_fields)
        return

    previous = Product.objects.filter(pk=instance.pk).values(*watched_fields).first()
    if previous is None:
        instance._auto_sync_changed_fields = sorted(watched_fields)
        return

    instance._auto_sync_changed_fields = sorted(
        field
        for field in watched_fields
        if previous.get(field) != getattr(instance, field)
    )


@receiver(post_save, sender=Product, dispatch_uid="products_enqueue_product_auto_sync_jobs")
def enqueue_product_auto_sync_jobs(sender, instance: Product, raw: bool = False, **kwargs):
    if raw or is_product_auto_sync_disabled():
        return

    changed_fields = list(getattr(instance, "_auto_sync_changed_fields", []) or [])
    _enqueue_product_sync_on_commit(
        product_id=instance.pk,
        changed_fields=changed_fields,
        trigger="product_save",
    )


@receiver(pre_save, sender=Price, dispatch_uid="products_capture_price_auto_sync_changes")
def capture_price_auto_sync_changes(sender, instance: Price, raw: bool = False, update_fields=None, **kwargs):
    if raw or is_product_auto_sync_disabled():
        instance._auto_sync_changed_fields = []
        return

    watched_fields = set(PRICE_AUTO_SYNC_FIELDS)
    if update_fields is not None:
        watched_fields &= {str(field) for field in update_fields}
        if not watched_fields:
            instance._auto_sync_changed_fields = []
            return

    if not instance.pk:
        instance._auto_sync_changed_fields = sorted(f"price.{field}" for field in watched_fields)
        return

    previous = Price.objects.filter(pk=instance.pk).values(*watched_fields).first()
    if previous is None:
        instance._auto_sync_changed_fields = sorted(f"price.{field}" for field in watched_fields)
        return

    instance._auto_sync_changed_fields = sorted(
        f"price.{field}"
        for field in watched_fields
        if previous.get(field) != getattr(instance, field)
    )


@receiver(post_save, sender=Price, dispatch_uid="products_enqueue_price_auto_sync_jobs")
def enqueue_price_auto_sync_jobs(sender, instance: Price, raw: bool = False, **kwargs):
    if raw or is_product_auto_sync_disabled():
        return

    _enqueue_product_sync_on_commit(
        product_id=instance.product_id,
        changed_fields=list(getattr(instance, "_auto_sync_changed_fields", []) or []),
        trigger="price_save",
    )


@receiver(pre_save, sender=Storage, dispatch_uid="products_capture_storage_auto_sync_changes")
def capture_storage_auto_sync_changes(sender, instance: Storage, raw: bool = False, update_fields=None, **kwargs):
    if raw or is_product_auto_sync_disabled():
        instance._auto_sync_changed_fields = []
        return

    watched_fields = set(STORAGE_AUTO_SYNC_FIELDS)
    if update_fields is not None:
        watched_fields &= {str(field) for field in update_fields}
        if not watched_fields:
            instance._auto_sync_changed_fields = []
            return

    if not instance.pk:
        instance._auto_sync_changed_fields = sorted(f"storage.{field}" for field in watched_fields)
        return

    previous = Storage.objects.filter(pk=instance.pk).values(*watched_fields).first()
    if previous is None:
        instance._auto_sync_changed_fields = sorted(f"storage.{field}" for field in watched_fields)
        return

    instance._auto_sync_changed_fields = sorted(
        f"storage.{field}"
        for field in watched_fields
        if previous.get(field) != getattr(instance, field)
    )


@receiver(post_save, sender=Storage, dispatch_uid="products_enqueue_storage_auto_sync_jobs")
def enqueue_storage_auto_sync_jobs(sender, instance: Storage, raw: bool = False, **kwargs):
    if raw or is_product_auto_sync_disabled():
        return

    _enqueue_product_sync_on_commit(
        product_id=instance.product_id,
        changed_fields=list(getattr(instance, "_auto_sync_changed_fields", []) or []),
        trigger="storage_save",
    )


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
