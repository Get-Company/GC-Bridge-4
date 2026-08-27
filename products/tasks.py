from __future__ import annotations

from collections.abc import Sequence

from celery import shared_task
from django.core.management import call_command

from core.live_events import emit_event, emit_run_finished, emit_run_started
from issues.services import TaskIssueCollector

PRODUCT_SYNC_CONTINUATION = "products.scheduled_product_sync_page"
PRODUCT_SYNC_SHOPWARE_BATCH_SIZE = 50


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


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index:index + size]) for index in range(0, len(values), size)]


def _enqueue_shopware_product_batches(
    *,
    erp_nrs: Sequence[str],
    include_images: bool,
    source_job_id: int | None = None,
) -> list[str]:
    """Publish bounded, idempotent Shopware-6 batches on the bulk queue.

    The GraphQL continuation must only turn a completed Microtech read into
    follow-up work.  It must never keep the continuation worker occupied for
    the full catalogue export.
    """
    cleaned = _erp_list(erp_nrs)
    task_ids: list[str] = []
    for batch_number, batch in enumerate(_chunks(cleaned, PRODUCT_SYNC_SHOPWARE_BATCH_SIZE), start=1):
        result = sync_shopware_product_batch.apply_async(
            kwargs={
                "erp_nrs": batch,
                "include_images": bool(include_images),
                "source_job_id": source_job_id,
                "batch_number": batch_number,
            },
            queue="bulk",
        )
        task_ids.append(str(result.id or ""))
    return task_ids


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


@shared_task(name="products.sync_variant_family_to_shopware")
def sync_variant_family_to_shopware(family_id: int) -> dict:
    """Synchronize one active variant family after an attribute-related save."""
    from products.models import ProductVariantFamily
    from shopware.services import ShopwareVariantSyncService

    family = (
        ProductVariantFamily.objects.select_related("target_category", "default_product")
        .filter(pk=family_id, is_active=True)
        .first()
    )
    if family is None:
        return {"family_id": family_id, "status": "skipped"}

    result = ShopwareVariantSyncService().sync(family)
    if result.errors:
        raise ValueError("; ".join(result.errors))

    return {
        "family_id": family.pk,
        "family_slug": result.family_slug,
        "parent_id": result.parent_id,
        "variant_count": result.variant_count,
        "detached_count": result.detached_count,
        "status": "succeeded",
    }


@shared_task(name="products.sync_category_to_shopware")
def sync_category_to_shopware(category_id: int) -> dict:
    """Synchronize one changed category, its translations, and its products to SW6."""
    from products.models import Category
    from shopware.services import ShopwareCategoryContentSyncService

    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        return {"category_id": category_id, "status": "skipped"}

    result = ShopwareCategoryContentSyncService().sync(category)
    return {
        "category_id": category.pk,
        "shopware_id": category.sw6_id,
        **result,
    }


@shared_task(name="products.sync_category_translations_to_shopware")
def sync_category_translations_to_shopware(category_id: int) -> dict:
    """Synchronize only customer-visible category translations to Shopware 6."""
    from products.models import Category
    from shopware.services import ShopwareCategoryTranslationSyncService

    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        return {"category_id": category_id, "status": "skipped"}

    synced = ShopwareCategoryTranslationSyncService().sync(category)
    return {
        "category_id": category.pk,
        "shopware_id": category.sw6_id,
        "status": "succeeded" if synced else "skipped",
    }


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
    """Legacy entry point that now only publishes bounded Shopware-6 work."""
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

    task_ids = _enqueue_shopware_product_batches(
        erp_nrs=_active_product_erp_nrs(limit=limit),
        include_images=bool(force_images),
    )
    logger.info("scheduled_product_sync finalize: {} Shopware-6-Batches eingereiht", len(task_ids))
    return {
        "expired": expired_count,
        "microtech_updated": mt_updated,
        "force_images": force_images,
        "shopware_batches": len(task_ids),
    }


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

    run_id = str(job.external_job_id)
    task_name = "products.scheduled_product_sync"
    emit_run_started(task_name, run_id, f"Microtech-Import gestartet ({len(products)} Datensätze)")
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
                emit_event(
                    task_name, entity=str(artikel_service.get_erp_nr() or ""),
                    step="microtech→django", status="ok",
                    summary=f"Produkt {artikel_service.get_erp_nr()} importiert",
                    run_id=run_id, target="django",
                )
            except Exception as exc:
                logger.warning("scheduled_product_sync: record error - {}", exc)
                state["errors"] += 1
                emit_event(
                    task_name,
                    entity=str(product_data.get("artNr") or product_data.get("erpNr") or ""),
                    step="microtech→django", status="skipped",
                    summary=f"Übersprungen: {exc}", run_id=run_id,
                    payload={"error": str(exc)},
                )
            state["processed"] += 1

    emit_run_finished(
        task_name, run_id,
        f"{state['processed']} verarbeitet, {state['success']} ok, {state['errors']} übersprungen",
        stats=state,
    )
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
    # After the import, publish small Shopware-6 tasks.  The continuation can
    # complete here; each output batch has its own retry/error state in Celery
    # and cannot monopolise the worker that advances GraphQL jobs.
    selected_erp_nrs = erp_nrs or _erp_list(
        product.get("artNr") or product.get("erpNr")
        for product in products[: state["processed"]]
    )
    task_ids = _enqueue_shopware_product_batches(
        erp_nrs=selected_erp_nrs,
        include_images=include_images,
        source_job_id=job.pk,
    )
    context["state"] = state
    context["shopware_batch_task_ids"] = task_ids
    context["shopware_batch_count"] = len(task_ids)
    job.context = context
    job.save(update_fields=("context", "updated_at"))


def _finalize_scheduled_product_sync(
    *,
    include_images: bool,
    limit: int | None = None,
    erp_nrs: Sequence[str] | None = None,
) -> list[str]:
    """Compatibility helper for callers that used the former serial finalizer."""
    cleaned_erp_nrs = _erp_list(erp_nrs) or _active_product_erp_nrs(limit=limit)
    return _enqueue_shopware_product_batches(
        erp_nrs=cleaned_erp_nrs,
        include_images=include_images,
    )


@shared_task(
    name="products.sync_shopware_product_batch",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=900,
    time_limit=960,
)
def sync_shopware_product_batch(
    task,
    *,
    erp_nrs: Sequence[str],
    include_images: bool = True,
    source_job_id: int | None = None,
    batch_number: int | None = None,
) -> dict:
    """Synchronize one finite catalogue slice plus its affected variants.

    Repeating this task is safe: Shopware upserts are keyed by product number
    and the variant command resolves the same persisted family definition.
    """
    from products.models import Product
    from products.services.variant_family import ProductVariantFamilyResolverService

    cleaned_erp_nrs = _erp_list(erp_nrs)
    if not cleaned_erp_nrs:
        return {"status": "skipped", "count": 0, "batch_number": batch_number}

    run_id = str(source_job_id or task.request.id or "")
    with TaskIssueCollector("products.sync_shopware_product_batch"):
        call_command("shopware_sync_products", *cleaned_erp_nrs, skip_images=True)
        if include_images:
            call_command("shopware_force_product_image_uploads", *cleaned_erp_nrs)

        resolver = ProductVariantFamilyResolverService()
        family_slugs = sorted(
            {
                family.slug
                for product in Product.objects.filter(erp_nr__in=cleaned_erp_nrs).only("id", "erp_nr")
                for family in resolver.families_for_product(product)
            }
        )
        if family_slugs:
            call_command(
                "shopware_sync_variants",
                *family_slugs,
                apply=True,
                skip_product_sync=True,
            )

    emit_event(
        "products.sync_shopware_product_batch",
        entity=", ".join(cleaned_erp_nrs[:3]),
        step=f"Batch {batch_number or '-'} → shopware6",
        status="ok",
        summary=f"{len(cleaned_erp_nrs)} Produkte und {len(family_slugs)} Variantenfamilien synchronisiert",
        run_id=run_id,
        target="shopware6",
    )
    return {
        "status": "succeeded",
        "count": len(cleaned_erp_nrs),
        "family_count": len(family_slugs),
        "batch_number": batch_number,
    }


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


@shared_task(name="products.sync_restored_price_increase")
def sync_restored_price_increase(erp_nrs: Sequence[str]) -> dict[str, int]:
    """Push restored Bridge prices to Microtech and Shopware 6."""
    cleaned_erp_nrs = _clean_erp_nrs(erp_nrs)
    if not cleaned_erp_nrs:
        return {"microtech": 0, "shopware": 0}

    call_command("microtech_update_prices", *cleaned_erp_nrs)
    call_command("shopware_sync_products", *cleaned_erp_nrs, skip_images=True)
    count = len(cleaned_erp_nrs)
    return {"microtech": count, "shopware": count}


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
