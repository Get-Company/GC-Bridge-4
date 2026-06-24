from __future__ import annotations

from collections.abc import Sequence

from celery import shared_task
from django.core.management import call_command


def _clean_erp_nrs(erp_nrs: Sequence[str] | None) -> list[str]:
    return [str(erp_nr).strip() for erp_nr in (erp_nrs or []) if str(erp_nr).strip()]


@shared_task(name="products.scheduled_product_sync")
def scheduled_product_sync(
    *,
    limit: int | None = None,
    exclude_inactive: bool = False,
    write_base_price_back: bool = False,
) -> None:
    call_command(
        "scheduled_product_sync",
        limit=limit,
        exclude_inactive=exclude_inactive,
        write_base_price_back=write_base_price_back,
    )


@shared_task(name="products.microtech_sync_products")
def microtech_sync_products(
    erp_nrs: Sequence[str] | None = None,
    *,
    sync_all: bool = False,
    include_inactive: bool = False,
    preserve_is_active: bool = False,
    limit: int | None = None,
) -> None:
    call_command(
        "microtech_sync_products",
        *_clean_erp_nrs(erp_nrs),
        all=sync_all,
        include_inactive=include_inactive,
        preserve_is_active=preserve_is_active,
        limit=limit,
    )


@shared_task(name="products.microtech_update_product")
def microtech_update_product(erp_nrs: Sequence[str]) -> None:
    call_command("microtech_update_product", *_clean_erp_nrs(erp_nrs))


@shared_task(name="products.microtech_update_prices")
def microtech_update_prices(erp_nrs: Sequence[str]) -> None:
    call_command("microtech_update_prices", *_clean_erp_nrs(erp_nrs))


@shared_task(name="products.shopware_sync_products")
def shopware_sync_products(
    erp_nrs: Sequence[str] | None = None,
    *,
    sync_all: bool = False,
    limit: int | None = None,
    batch_size: int = 50,
    only_with_images: bool = False,
    log_images: bool = False,
) -> None:
    call_command(
        "shopware_sync_products",
        *_clean_erp_nrs(erp_nrs),
        all=sync_all,
        limit=limit,
        batch_size=batch_size,
        only_with_images=only_with_images,
        log_images=log_images,
    )


@shared_task(name="products.shopware_force_product_image_uploads")
def shopware_force_product_image_uploads(
    erp_nrs: Sequence[str] | None = None,
    *,
    sync_all: bool = False,
    limit: int | None = None,
    batch_size: int = 10,
    only_with_images: bool = False,
    log_images: bool = False,
) -> None:
    call_command(
        "shopware_force_product_image_uploads",
        *_clean_erp_nrs(erp_nrs),
        all=sync_all,
        limit=limit,
        batch_size=batch_size,
        only_with_images=only_with_images,
        log_images=log_images,
    )
