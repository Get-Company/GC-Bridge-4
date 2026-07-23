from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import Signal, receiver
from loguru import logger

from products.models import (
    Price,
    PriceIncrease,
    Product,
    ProductVariantAttribute,
    ProductVariantFamily,
    PropertyGroup,
    PropertyValue,
    Storage,
)
from products.services import ProductAutoSyncService, is_product_auto_sync_disabled
from shopware.models import ShopwareSettings

price_increase_applied = Signal()

MIN_PRICE_FACTOR = Decimal("0.01")
MAX_PRICE_FACTOR = Decimal("10.00")
PRODUCT_AUTO_SYNC_FIELDS = (
    "erp_nr",
    "gtin",
    "name",
    "name_de",
    "name_en",
    "name_ch_de",
    "name_it_de",
    "name_it_it",
    "sort_order",
    "description",
    "description_de",
    "description_en",
    "description_ch_de",
    "description_it_de",
    "description_it_it",
    "description_short",
    "description_short_de",
    "description_short_en",
    "description_short_ch_de",
    "description_short_it_de",
    "description_short_it_it",
    "is_active",
    "factor",
    "unit",
    "unit_de",
    "unit_en",
    "unit_ch_de",
    "unit_it_de",
    "unit_it_it",
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
PROPERTY_GROUP_VARIANT_SYNC_FIELDS = (
    "external_key",
    "name",
)
PROPERTY_VALUE_VARIANT_SYNC_FIELDS = (
    "external_key",
    "group_id",
    "image_id",
    "name",
)
VARIANT_ATTRIBUTE_SYNC_FIELDS = (
    "display_type",
    "fallback_value_id",
    "family_id",
    "position",
    "property_group_id",
)
VARIANT_FAMILY_SYNC_FIELDS = (
    "default_product_id",
    "description",
    "is_active",
    "name",
    "shopware_product_number",
    "slug",
    "target_category_id",
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


def _watched_fields_for_save(*, watched_fields: tuple[str, ...], update_fields) -> set[str]:
    """Return watched model attnames that can be affected by this save call."""
    watched = set(watched_fields)
    if update_fields is None:
        return watched

    updated = {str(field) for field in update_fields}
    return {
        field
        for field in watched
        if field in updated or (field.endswith("_id") and field[:-3] in updated)
    }


def _changed_fields_before_save(*, model, instance, watched_fields: tuple[str, ...], update_fields) -> set[str]:
    watched = _watched_fields_for_save(watched_fields=watched_fields, update_fields=update_fields)
    if not watched:
        return set()
    if not instance.pk:
        return watched

    previous = model.objects.filter(pk=instance.pk).values(*watched).first()
    if previous is None:
        return watched
    return {field for field in watched if previous.get(field) != getattr(instance, field)}


def _active_variant_family_ids_for_groups(group_ids: set[int | None]) -> set[int]:
    relevant_group_ids = {group_id for group_id in group_ids if group_id}
    if not relevant_group_ids:
        return set()
    return set(
        ProductVariantAttribute.objects.filter(
            family__is_active=True,
            property_group_id__in=relevant_group_ids,
        ).values_list("family_id", flat=True)
    )


def _enqueue_variant_family_sync_on_commit(*, family_ids: set[int]) -> None:
    if not family_ids:
        return

    for family_id in sorted(family_ids):
        def enqueue_after_commit(family_id=family_id) -> None:
            from products.tasks import sync_variant_family_to_shopware

            try:
                sync_variant_family_to_shopware.delay(family_id)
            except Exception as exc:
                logger.warning(
                    "Could not enqueue automatic Shopware variant sync for family {}: {}",
                    family_id,
                    exc,
                )

        transaction.on_commit(enqueue_after_commit)


@receiver(pre_save, sender=ProductVariantFamily, dispatch_uid="products_capture_variant_family_sync_changes")
def capture_variant_family_sync_changes(
    sender,
    instance: ProductVariantFamily,
    raw: bool = False,
    update_fields=None,
    **kwargs,
):
    if raw or is_product_auto_sync_disabled():
        instance._variant_family_sync_ids = set()
        return

    changed_fields = _changed_fields_before_save(
        model=ProductVariantFamily,
        instance=instance,
        watched_fields=VARIANT_FAMILY_SYNC_FIELDS,
        update_fields=update_fields,
    )
    instance._variant_family_sync_ids = {instance.pk} if changed_fields and instance.pk else set()


@receiver(post_save, sender=ProductVariantFamily, dispatch_uid="products_enqueue_variant_family_sync")
def enqueue_variant_family_sync(
    sender,
    instance: ProductVariantFamily,
    created: bool = False,
    raw: bool = False,
    **kwargs,
):
    if raw or is_product_auto_sync_disabled():
        return

    _enqueue_variant_family_sync_on_commit(
        family_ids=(
            {instance.pk}
            if created and instance.pk
            else set(getattr(instance, "_variant_family_sync_ids", set()) or set())
        )
    )


@receiver(
    m2m_changed,
    sender=ProductVariantFamily.source_categories.through,
    dispatch_uid="products_enqueue_variant_family_source_categories_sync",
)
def enqueue_variant_family_source_categories_sync(
    sender,
    instance,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
):
    if is_product_auto_sync_disabled() or action not in {"post_add", "post_remove", "post_clear"}:
        return

    family_ids = set()
    if reverse:
        family_ids = {family_id for family_id in (pk_set or set()) if family_id}
    elif instance.pk:
        family_ids = {instance.pk}
    _enqueue_variant_family_sync_on_commit(family_ids=family_ids)


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


@receiver(pre_save, sender=ProductVariantAttribute, dispatch_uid="products_capture_variant_attribute_sync_changes")
def capture_variant_attribute_sync_changes(
    sender,
    instance: ProductVariantAttribute,
    raw: bool = False,
    update_fields=None,
    **kwargs,
):
    if raw or is_product_auto_sync_disabled():
        instance._variant_sync_family_ids = set()
        return

    changed_fields = _changed_fields_before_save(
        model=ProductVariantAttribute,
        instance=instance,
        watched_fields=VARIANT_ATTRIBUTE_SYNC_FIELDS,
        update_fields=update_fields,
    )
    if not changed_fields:
        instance._variant_sync_family_ids = set()
        return

    family_ids = {instance.family_id} if instance.family_id else set()
    if instance.pk and "family_id" in changed_fields:
        previous_family_id = (
            ProductVariantAttribute.objects.filter(pk=instance.pk)
            .values_list("family_id", flat=True)
            .first()
        )
        if previous_family_id:
            family_ids.add(previous_family_id)
    instance._variant_sync_family_ids = family_ids


@receiver(post_save, sender=ProductVariantAttribute, dispatch_uid="products_enqueue_variant_attribute_sync")
def enqueue_variant_attribute_sync(sender, instance: ProductVariantAttribute, raw: bool = False, **kwargs):
    if raw or is_product_auto_sync_disabled():
        return

    _enqueue_variant_family_sync_on_commit(
        family_ids=set(getattr(instance, "_variant_sync_family_ids", set()) or set())
    )


@receiver(post_delete, sender=ProductVariantAttribute, dispatch_uid="products_enqueue_deleted_variant_attribute_sync")
def enqueue_deleted_variant_attribute_sync(sender, instance: ProductVariantAttribute, **kwargs):
    if is_product_auto_sync_disabled():
        return

    _enqueue_variant_family_sync_on_commit(
        family_ids={instance.family_id} if instance.family_id else set()
    )


@receiver(pre_save, sender=PropertyGroup, dispatch_uid="products_capture_property_group_variant_sync_changes")
def capture_property_group_variant_sync_changes(
    sender,
    instance: PropertyGroup,
    raw: bool = False,
    update_fields=None,
    **kwargs,
):
    if raw or is_product_auto_sync_disabled():
        instance._variant_sync_group_ids = set()
        return

    changed_fields = _changed_fields_before_save(
        model=PropertyGroup,
        instance=instance,
        watched_fields=PROPERTY_GROUP_VARIANT_SYNC_FIELDS,
        update_fields=update_fields,
    )
    instance._variant_sync_group_ids = {instance.pk} if changed_fields and instance.pk else set()


@receiver(post_save, sender=PropertyGroup, dispatch_uid="products_enqueue_property_group_variant_sync")
def enqueue_property_group_variant_sync(sender, instance: PropertyGroup, raw: bool = False, **kwargs):
    if raw or is_product_auto_sync_disabled():
        return

    _enqueue_variant_family_sync_on_commit(
        family_ids=_active_variant_family_ids_for_groups(
            set(getattr(instance, "_variant_sync_group_ids", set()) or set())
        )
    )


@receiver(pre_save, sender=PropertyValue, dispatch_uid="products_capture_property_value_variant_sync_changes")
def capture_property_value_variant_sync_changes(
    sender,
    instance: PropertyValue,
    raw: bool = False,
    update_fields=None,
    **kwargs,
):
    if raw or is_product_auto_sync_disabled():
        instance._variant_sync_group_ids = set()
        return

    changed_fields = _changed_fields_before_save(
        model=PropertyValue,
        instance=instance,
        watched_fields=PROPERTY_VALUE_VARIANT_SYNC_FIELDS,
        update_fields=update_fields,
    )
    if not changed_fields:
        instance._variant_sync_group_ids = set()
        return

    group_ids = {instance.group_id} if instance.group_id else set()
    if instance.pk and "group_id" in changed_fields:
        previous_group_id = (
            PropertyValue.objects.filter(pk=instance.pk)
            .values_list("group_id", flat=True)
            .first()
        )
        if previous_group_id:
            group_ids.add(previous_group_id)
    instance._variant_sync_group_ids = group_ids


@receiver(post_save, sender=PropertyValue, dispatch_uid="products_enqueue_property_value_variant_sync")
def enqueue_property_value_variant_sync(sender, instance: PropertyValue, raw: bool = False, **kwargs):
    if raw or is_product_auto_sync_disabled():
        return

    _enqueue_variant_family_sync_on_commit(
        family_ids=_active_variant_family_ids_for_groups(
            set(getattr(instance, "_variant_sync_group_ids", set()) or set())
        )
    )


@receiver(post_delete, sender=PropertyValue, dispatch_uid="products_enqueue_deleted_property_value_variant_sync")
def enqueue_deleted_property_value_variant_sync(sender, instance: PropertyValue, **kwargs):
    if is_product_auto_sync_disabled():
        return

    _enqueue_variant_family_sync_on_commit(
        family_ids=_active_variant_family_ids_for_groups({instance.group_id})
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
