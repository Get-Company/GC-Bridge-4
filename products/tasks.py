from __future__ import annotations

from collections.abc import Sequence

from celery import shared_task
from django.core.management import call_command

from issues.services import TaskIssueCollector


def _erp_list(erp_nrs: Sequence[str] | None) -> list[str]:
    return [str(nr).strip() for nr in (erp_nrs or []) if str(nr).strip()]


@shared_task(name="products.sync_from_microtech")
def sync_from_microtech(
    erp_nrs: Sequence[str] | None = None,
    *,
    texts_and_prices_only: bool = False,
) -> None:
    cleaned = _erp_list(erp_nrs)
    with TaskIssueCollector("products.sync_from_microtech"):
        if cleaned:
            call_command(
                "microtech_sync_products",
                *cleaned,
                include_inactive=True,
                preserve_is_active=True,
                skip_images=texts_and_prices_only,
            )
        else:
            call_command(
                "microtech_sync_products",
                all=True,
                include_inactive=True,
                preserve_is_active=True,
                skip_images=texts_and_prices_only,
            )


@shared_task(name="products.sync_to_shopware")
def sync_to_shopware(
    erp_nrs: Sequence[str] | None = None,
    *,
    texts_and_prices_only: bool = False,
) -> None:
    cleaned = _erp_list(erp_nrs)
    with TaskIssueCollector("products.sync_to_shopware"):
        if cleaned:
            call_command(
                "shopware_sync_products",
                *cleaned,
                skip_images=texts_and_prices_only,
            )
        else:
            call_command(
                "shopware_sync_products",
                all=True,
                skip_images=texts_and_prices_only,
            )


@shared_task(name="products.sync_to_microtech")
def sync_to_microtech(erp_nrs: Sequence[str] | None = None) -> None:
    cleaned = _erp_list(erp_nrs)
    with TaskIssueCollector("products.sync_to_microtech"):
        if cleaned:
            call_command("microtech_update_product", *cleaned)
            call_command("microtech_update_prices", *cleaned)
        else:
            call_command("microtech_update_product", all=True)
            call_command("microtech_update_prices", all=True)


@shared_task(name="products.quick_product_sync")
def quick_product_sync() -> None:
    """Texte, Preise und Lagerbestand synchronisieren — ohne Bilder.

    Reihenfolge: Microtech → Django, dann Django → Shopware.
    Gedacht für stündliche oder halbtagliche Beat-Schedules (07:00, 13:00).
    Bilder werden übersprungen (skip_images=True). Sonderpreis-Bereinigung
    läuft separat über expire_special_prices (stündlich).
    """
    from loguru import logger
    from core.logging import add_managed_file_sink

    sink_id, log_path = add_managed_file_sink(
        "quick_product_sync", category="weekly"
    )
    try:
        logger.info("Quick product sync started (skip_images=True)")
        with TaskIssueCollector("products.quick_product_sync"):
            call_command(
                "microtech_sync_products",
                all=True,
                include_inactive=True,
                preserve_is_active=True,
                skip_images=True,
            )
            logger.info("Quick product sync: Microtech → Django done, starting Django → Shopware")
            call_command("shopware_sync_products", all=True, skip_images=True)
        logger.info("Quick product sync finished. log_file={}", log_path)
    except Exception:
        logger.exception("Quick product sync failed. log_file={}", log_path)
        raise
    finally:
        logger.remove(sink_id)


@shared_task(name="products.expire_special_prices")
def expire_special_prices() -> dict:
    from microtech.services import MicrotechExpiredSpecialSyncService, microtech_connection
    from django.utils import timezone

    with TaskIssueCollector("products.expire_special_prices"):
        expired_count, affected_ids = MicrotechExpiredSpecialSyncService().clear_expired_specials(now=timezone.now())
        if not affected_ids:
            return {"expired": 0, "microtech_updated": 0, "shopware_queued": 0}

        with microtech_connection() as erp:
            mt_updated, _ = MicrotechExpiredSpecialSyncService().sync_expired_specials_to_microtech(
                erp=erp,
                affected_product_ids=affected_ids,
            )

        from products.models import Product
        erp_nrs = list(
            Product.objects.filter(pk__in=affected_ids).values_list("erp_nr", flat=True)
        )
        sync_to_shopware.delay(erp_nrs, texts_and_prices_only=True)

    return {"expired": expired_count, "microtech_updated": mt_updated, "shopware_queued": len(erp_nrs)}


@shared_task(name="products.process_product_sync_job")
def process_product_sync_job(job_id: int) -> None:
    from products.services import ProductAutoSyncService

    ProductAutoSyncService().process_job(job_id=job_id)


# ---------------------------------------------------------------------------
# Legacy tasks kept for backwards-compatibility with existing Celery beat
# schedules and any callers that may still reference these task names.
# ---------------------------------------------------------------------------

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
    skip_images: bool = False,
) -> None:
    command_options = {
        "all": sync_all,
        "limit": limit,
        "batch_size": batch_size,
        "only_with_images": only_with_images,
        "log_images": log_images,
    }
    if skip_images:
        command_options["skip_images"] = True
    call_command(
        "shopware_sync_products",
        *_clean_erp_nrs(erp_nrs),
        **command_options,
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
