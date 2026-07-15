from __future__ import annotations

from collections.abc import Sequence

from celery import shared_task
from django.core.management import call_command

from issues.services import TaskIssueCollector

PRODUCT_SYNC_CONTINUATION = "products.scheduled_product_sync_page"


def _erp_list(erp_nrs: Sequence[str] | None) -> list[str]:
    return [str(nr).strip() for nr in (erp_nrs or []) if str(nr).strip()]


def _coerce_optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _active_product_erp_nrs(*, limit: int | None = None) -> list[str]:
    from products.models import Product

    queryset = (
        Product.objects.filter(is_active=True)
        .exclude(erp_nr__isnull=True)
        .exclude(erp_nr="")
        .order_by("erp_nr")
        .values_list("erp_nr", flat=True)
    )
    if limit:
        queryset = queryset[:limit]
    return _erp_list(queryset)


@shared_task(
    name="products.sync_from_microtech",
)
def sync_from_microtech(
    erp_nrs: Sequence[str] | None = None,
    *,
    texts_and_prices_only: bool = False,
    include_inactive: bool = True,
    **_deprecated_options,
) -> dict | None:
    """Deprecated alias for the unified Microtech -> Django -> Shopware product sync."""
    return scheduled_product_sync.run(
        erp_nrs=erp_nrs,
        include_images=not texts_and_prices_only,
        exclude_inactive=not include_inactive,
    )


@shared_task(name="products.sync_to_shopware")
def sync_to_shopware(
    erp_nrs: Sequence[str] | None = None,
    *,
    texts_and_prices_only: bool = False,
) -> None:
    """Deprecated alias for the unified product sync."""
    return scheduled_product_sync.run(erp_nrs=erp_nrs, include_images=not texts_and_prices_only)


@shared_task(name="products.sync_to_microtech")
def sync_to_microtech(erp_nrs: Sequence[str] | None = None) -> None:
    """Deprecated product-sync alias. Product reads now flow Microtech -> Django -> Shopware."""
    return scheduled_product_sync.run(erp_nrs=erp_nrs, include_images=False)


@shared_task(name="products.quick_product_sync")
def quick_product_sync() -> None:
    """Start the unified product sync without image rebuilds."""
    from loguru import logger

    logger.info("quick_product_sync: scheduling products.scheduled_product_sync (include_images=False)")
    scheduled_product_sync.delay(include_images=False)


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
        scheduled_product_sync.delay(erp_nrs=erp_nrs, include_images=False)

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


@shared_task(name="products._scheduled_product_sync_finalize")
def _scheduled_product_sync_finalize(
    *,
    limit: int | None = None,
    write_base_price_back: bool = False,
    force_images: bool = True,
) -> dict:
    """Schritte 2–5 des vollständigen Produkt-Syncs nach dem Microtech-Import."""
    from loguru import logger
    from microtech.services import MicrotechExpiredSpecialSyncService, microtech_connection
    from django.utils import timezone

    logger.info("scheduled_product_sync finalize: Sonderpreise bereinigen")
    expired_count, affected_ids = MicrotechExpiredSpecialSyncService().clear_expired_specials(now=timezone.now())
    mt_updated = 0
    if affected_ids:
        with microtech_connection() as erp:
            mt_updated, _ = MicrotechExpiredSpecialSyncService().sync_expired_specials_to_microtech(
                erp=erp,
                affected_product_ids=affected_ids,
                write_base_price_back=write_base_price_back,
            )
        logger.info("Sonderpreise: {} abgelaufen, {} in Microtech aktualisiert", expired_count, mt_updated)

    logger.info("scheduled_product_sync finalize: Django → Shopware")
    with TaskIssueCollector("products.scheduled_product_sync"):
        call_command("shopware_sync_products", all=True, limit=limit)
        if force_images:
            logger.info("scheduled_product_sync finalize: Shopware Bilder force-upload")
            call_command("shopware_force_product_image_uploads", all=True, limit=limit)

    return {"expired": expired_count, "microtech_updated": mt_updated, "force_images": force_images}


@shared_task(name="products.scheduled_product_sync")
def scheduled_product_sync(
    *,
    erp_nrs: Sequence[str] | None = None,
    include_images: bool | None = None,
    limit: int | None = None,
    exclude_inactive: bool = False,
    write_base_price_back: bool = False,
    force_images: bool | None = None,
) -> dict:
    from loguru import logger
    from microtech.services import MicrotechJobSentinelService

    if include_images is None:
        include_images = True if force_images is None else bool(force_images)
    requested_erp_nrs = _erp_list(erp_nrs)
    limit = _coerce_optional_int(limit)
    mode = "selected" if requested_erp_nrs else "active"
    cleaned_erp_nrs = requested_erp_nrs or _active_product_erp_nrs(limit=limit)
    context = {
        "source": "products.scheduled_product_sync",
        "mode": mode,
        "erp_nrs": cleaned_erp_nrs,
        "include_images": bool(include_images),
        "include_inactive": False if mode == "active" else not exclude_inactive,
        "limit": limit,
        "state": {"success": 0, "errors": 0, "processed": 0},
    }
    if write_base_price_back:
        logger.warning(
            "scheduled_product_sync ignores deprecated write_base_price_back=True; "
            "the unified task only runs Microtech -> Django -> Shopware."
        )
    if exclude_inactive:
        logger.warning(
            "scheduled_product_sync uses Django active product selection for full sync; "
            "Microtech dataset inactive filters are not sent."
        )
    if not cleaned_erp_nrs:
        logger.warning("scheduled_product_sync: no active Django products with ERP number found.")
        return {
            "job_id": None,
            "external_job_id": None,
            "include_images": bool(include_images),
            "mode": context["mode"],
            "count": 0,
        }
    logger.info(
        "scheduled_product_sync: Sentinel Produkt-Batch starten (mode={}, count={}, include_images={}, limit={})",
        context["mode"],
        len(cleaned_erp_nrs),
        include_images,
        limit,
    )
    job = MicrotechJobSentinelService().submit_product_batch_read(
        erp_numbers=cleaned_erp_nrs,
        include_images=bool(include_images),
        continuation=PRODUCT_SYNC_CONTINUATION,
        context=context,
        next_step="Produkt-Batch aus Microtech importieren.",
    )
    return {
        "job_id": job.pk,
        "external_job_id": job.external_job_id,
        "include_images": bool(include_images),
        "mode": context["mode"],
        "count": len(cleaned_erp_nrs),
    }


def _scheduled_product_sync_continuation(job) -> None:
    from loguru import logger
    from microtech.management.commands.microtech_sync_products import (
        Command as SyncCommand,
        _get_admin_user_id,
    )
    from microtech.services import (
        MicrotechExpiredSpecialSyncService,
        MicrotechGraphQLClientService,
    )
    from microtech.services.artikel import MicrotechArtikelService
    from django.contrib.contenttypes.models import ContentType
    from products.models import Product as ProductModel
    from products.services import disable_product_auto_sync

    context = dict(job.context or {})
    mode = str(context.get("mode") or "all")
    erp_nrs = _erp_list(context.get("erp_nrs"))
    include_images = bool(context.get("include_images", True))
    limit = _coerce_optional_int(context.get("limit"))
    state = dict(context.get("state") or {})
    state.setdefault("success", 0)
    state.setdefault("errors", 0)
    state.setdefault("processed", 0)

    client = MicrotechGraphQLClientService()
    result = client.product_list_job(str(job.external_job_id))
    products = result.get("products") or []
    artikel_service = MicrotechArtikelService(erp=client)
    # GraphQL product jobs already contain stock and storageLocation.
    lager_service = None
    tax_map = SyncCommand._ensure_taxes()
    cmd = SyncCommand()
    admin_user_id = _get_admin_user_id()
    content_type_id = ContentType.objects.get_for_model(ProductModel).id if admin_user_id else None

    with TaskIssueCollector("products.scheduled_product_sync"), disable_product_auto_sync():
        for product_data in products:
            if limit and state["processed"] >= limit:
                break
            try:
                artikel_service.load_product_record(product_data)
                if artikel_service.range_eof():
                    state["errors"] += 1
                    state["processed"] += 1
                    continue
                cmd._sync_current_record(
                    artikel_service,
                    lager_service,
                    tax_map=tax_map,
                    admin_user_id=admin_user_id,
                    content_type_id=content_type_id,
                    preserve_is_active=True,
                    skip_images=not include_images,
                )
                state["success"] += 1
            except Exception as exc:
                logger.warning("scheduled_product_sync: record error - {}", exc)
                state["errors"] += 1
            state["processed"] += 1

    logger.info(
        "scheduled_product_sync: Microtech import complete (processed={}, success={}, errors={}, include_images={})",
        state["processed"],
        state["success"],
        state["errors"],
        include_images,
    )
    expired_special_service = MicrotechExpiredSpecialSyncService()
    expired_count, affected_product_ids = expired_special_service.clear_expired_specials()
    if affected_product_ids:
        restored_count, _ = expired_special_service.sync_expired_specials_to_microtech(
            erp=client,
            affected_product_ids=affected_product_ids,
        )
        logger.info(
            "scheduled_product_sync: abgelaufene Sonderpreise bereinigt (prices={}, products={})",
            expired_count,
            restored_count,
        )
    _finalize_scheduled_product_sync(
        include_images=include_images,
        limit=None if erp_nrs else limit,
        erp_nrs=erp_nrs or None,
    )


def _finalize_scheduled_product_sync(
    *,
    include_images: bool,
    limit: int | None = None,
    erp_nrs: Sequence[str] | None = None,
) -> None:
    from loguru import logger

    cleaned_erp_nrs = _erp_list(erp_nrs)
    with TaskIssueCollector("products.scheduled_product_sync"):
        logger.info("scheduled_product_sync: Django -> Shopware ohne Bild-Medien starten")
        if cleaned_erp_nrs:
            call_command("shopware_sync_products", *cleaned_erp_nrs, skip_images=True)
        else:
            call_command(
                "shopware_sync_products",
                all=True,
                limit=limit,
                skip_images=True,
            )
        logger.info("scheduled_product_sync: Django -> Shopware5 starten")
        if cleaned_erp_nrs:
            call_command("shopware5_sync_products", *cleaned_erp_nrs)
        else:
            call_command("shopware5_sync_products", limit=limit)
        if include_images:
            logger.info("scheduled_product_sync: Shopware Bilder loeschen und neu hochladen")
            if cleaned_erp_nrs:
                call_command("shopware_force_product_image_uploads", *cleaned_erp_nrs)
            else:
                call_command(
                    "shopware_force_product_image_uploads",
                    all=True,
                    limit=limit,
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
    return scheduled_product_sync.run(
        erp_nrs=None if sync_all else _clean_erp_nrs(erp_nrs),
        include_images=False,
        exclude_inactive=not include_inactive,
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
    return scheduled_product_sync.run(
        erp_nrs=None if sync_all else _clean_erp_nrs(erp_nrs),
        include_images=not skip_images,
        limit=limit,
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
    return scheduled_product_sync.run(
        erp_nrs=None if sync_all else _clean_erp_nrs(erp_nrs),
        include_images=True,
        limit=limit,
    )


def register_product_sync_continuations() -> None:
    from microtech.services import register_continuation

    register_continuation(PRODUCT_SYNC_CONTINUATION, _scheduled_product_sync_continuation)


register_product_sync_continuations()
