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


def _build_product_dataset_input(
    *,
    include_inactive: bool = True,
    include_images: bool = True,
    find_key: list | None = None,
    after: list | None = None,
) -> dict:
    from microtech.services.artikel import MicrotechArtikelService

    fields = list(MicrotechArtikelService.default_fields)
    if not include_images:
        image_fields = set(MicrotechArtikelService.PRODUCT_IMAGE_FIELDS)
        fields = [field for field in fields if field not in image_fields]

    input_data: dict = {
        "dataset": MicrotechArtikelService.dataset_name,
        "fields": fields,
        "limit": MicrotechArtikelService.page_limit,
        "indexField": MicrotechArtikelService.index_field,
    }
    if find_key is not None:
        input_data["findKey"] = find_key
        input_data["limit"] = 1
        return input_data

    input_data["range"] = {"fromValues": ["000000"], "toValues": ["99999999ZZ"]}
    if not include_inactive:
        input_data["filter"] = "WBSHpKZ = 1"
    if after:
        input_data["after"] = after
    return input_data


@shared_task(
    bind=True,
    name="products.sync_from_microtech",
    max_retries=300,
)
def sync_from_microtech(
    self,
    erp_nrs: Sequence[str] | None = None,
    *,
    texts_and_prices_only: bool = False,
    include_inactive: bool = True,
    _job_id: str | None = None,
    _next_cursor: list | None = None,
    _state: dict | None = None,
) -> dict | None:
    """Microtech → Django (async Celery-Retry-Pattern für Bulk-Sync, synchron für einzelne ERPs)."""
    from loguru import logger
    from microtech.services.graphql_client import MicrotechGraphQLClientService
    from microtech.services.artikel import MicrotechArtikelService

    cleaned = _erp_list(erp_nrs)

    # Einzelne ERP-Nummern: synchroner Pfad (individuelle Produktabfragen, schnell)
    if cleaned:
        with TaskIssueCollector("products.sync_from_microtech"):
            call_command(
                "microtech_sync_products",
                *cleaned,
                include_inactive=True,
                preserve_is_active=True,
                skip_images=texts_and_prices_only,
            )
        return {"mode": "selected", "count": len(cleaned)}

    # Alle Produkte: asynchroner Job-Polling-Pfad
    client = MicrotechGraphQLClientService()
    state = _state or {"success": 0, "errors": 0, "processed": 0}

    retry_kwargs = {
        "erp_nrs": erp_nrs,
        "texts_and_prices_only": texts_and_prices_only,
        "include_inactive": include_inactive,
        "_next_cursor": _next_cursor,
        "_state": state,
    }

    if _job_id is None:
        # Phase 1: Dataset-Job einreichen, sofort zurückkehren
        input_data: dict = {
            "dataset": MicrotechArtikelService.dataset_name,
            "fields": list(MicrotechArtikelService.default_fields),
            "limit": MicrotechArtikelService.page_limit,
            "indexField": MicrotechArtikelService.index_field,
            "range": {"fromValues": ["000000"], "toValues": ["99999999ZZ"]},
        }
        if not include_inactive:
            input_data["filter"] = "WBSHpKZ = 1"
        if _next_cursor:
            input_data["after"] = _next_cursor

        job_id, retry_after = client.submit_dataset_job(input_data)
        countdown = max(int(retry_after), 15)
        logger.info("sync_from_microtech: job {} submitted, check in {}s", job_id, countdown)
        raise self.retry(countdown=countdown, kwargs={**retry_kwargs, "_job_id": job_id})

    # Phase 2: Einmalig prüfen ob Job fertig (kein Blockieren)
    result = client.check_dataset_job_once(_job_id)
    if result is None:
        logger.debug("sync_from_microtech: job {} still running, retry in 30s", _job_id)
        raise self.retry(countdown=30, kwargs={**retry_kwargs, "_job_id": _job_id})

    # Phase 3: Seite verarbeiten
    logger.info(
        "sync_from_microtech: job {} done — {} records",
        _job_id,
        result.get("returnedCount", "?"),
    )
    from microtech.services.lager import MicrotechLagerService
    from microtech.management.commands.microtech_sync_products import (
        Command as SyncCommand,
        _get_admin_user_id,
    )
    from django.contrib.contenttypes.models import ContentType
    from products.models import Product as ProductModel
    from products.services import disable_product_auto_sync

    artikel_service = MicrotechArtikelService(erp=client)
    artikel_service.load_result(result)
    lager_service = MicrotechLagerService(erp=client)
    tax_map = SyncCommand._ensure_taxes()
    cmd = SyncCommand()
    admin_user_id = _get_admin_user_id()
    content_type_id = ContentType.objects.get_for_model(ProductModel).id if admin_user_id else None

    with TaskIssueCollector("products.sync_from_microtech"), disable_product_auto_sync():
        while not artikel_service.range_eof():
            try:
                cmd._sync_current_record(
                    artikel_service,
                    lager_service,
                    tax_map=tax_map,
                    admin_user_id=admin_user_id,
                    content_type_id=content_type_id,
                    preserve_is_active=True,
                    skip_images=texts_and_prices_only,
                )
                state["success"] += 1
            except Exception as exc:
                logger.warning("sync_from_microtech: record error — {}", exc)
                state["errors"] += 1
            state["processed"] += 1
            artikel_service.range_next()

    if result.get("hasMore"):
        logger.info("sync_from_microtech: more pages, submitting next job")
        raise self.retry(
            countdown=5,
            kwargs={**retry_kwargs, "_job_id": None, "_next_cursor": result.get("nextCursor"), "_state": state},
        )

    logger.info(
        "sync_from_microtech: complete — success={}, errors={}, processed={}",
        state["success"],
        state["errors"],
        state["processed"],
    )
    return state


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

    Startet eine Celery-Chain: sync_from_microtech → sync_to_shopware.
    Beide Tasks laufen asynchron, quick_product_sync selbst kehrt sofort zurück.
    """
    from celery import chain as celery_chain
    from loguru import logger

    logger.info("quick_product_sync: chaining sync_from_microtech → sync_to_shopware (skip_images=True)")
    celery_chain(
        sync_from_microtech.si(texts_and_prices_only=True),
        sync_to_shopware.si(texts_and_prices_only=True),
    ).delay()


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
    cleaned_erp_nrs = _erp_list(erp_nrs)
    limit = _coerce_optional_int(limit)
    include_inactive = not exclude_inactive
    context = {
        "source": "products.scheduled_product_sync",
        "mode": "selected" if cleaned_erp_nrs else "all",
        "erp_nrs": cleaned_erp_nrs,
        "selected_index": 0,
        "include_images": bool(include_images),
        "include_inactive": include_inactive,
        "limit": limit,
        "state": {"success": 0, "errors": 0, "processed": 0},
    }
    if write_base_price_back:
        logger.warning(
            "scheduled_product_sync ignores deprecated write_base_price_back=True; "
            "the unified task only runs Microtech -> Django -> Shopware."
        )
    logger.info(
        "scheduled_product_sync: Sentinel import starten (mode={}, count={}, include_inactive={}, include_images={}, limit={})",
        context["mode"],
        len(cleaned_erp_nrs) if cleaned_erp_nrs else "all",
        include_inactive,
        include_images,
        limit,
    )
    input_data = _build_product_dataset_input(
        include_inactive=include_inactive,
        include_images=bool(include_images),
        find_key=[cleaned_erp_nrs[0]] if cleaned_erp_nrs else None,
    )
    job = MicrotechJobSentinelService().submit_dataset_records(
        input_data=input_data,
        continuation=PRODUCT_SYNC_CONTINUATION,
        context=context,
        next_step="Produktseite aus Microtech importieren.",
    )
    return {
        "job_id": job.pk,
        "external_job_id": job.external_job_id,
        "include_images": bool(include_images),
        "mode": context["mode"],
        "count": len(cleaned_erp_nrs) if cleaned_erp_nrs else None,
    }


def _scheduled_product_sync_continuation(job) -> None:
    from loguru import logger
    from microtech.management.commands.microtech_sync_products import (
        Command as SyncCommand,
        _get_admin_user_id,
    )
    from microtech.services import MicrotechGraphQLClientService, MicrotechJobSentinelService
    from microtech.services.artikel import MicrotechArtikelService
    from microtech.services.lager import MicrotechLagerService
    from django.contrib.contenttypes.models import ContentType
    from products.models import Product as ProductModel
    from products.services import disable_product_auto_sync

    context = dict(job.context or {})
    mode = str(context.get("mode") or "all")
    erp_nrs = _erp_list(context.get("erp_nrs"))
    selected_index = _coerce_optional_int(context.get("selected_index")) or 0
    include_images = bool(context.get("include_images", True))
    include_inactive = bool(context.get("include_inactive", True))
    limit = _coerce_optional_int(context.get("limit"))
    state = dict(context.get("state") or {})
    state.setdefault("success", 0)
    state.setdefault("errors", 0)
    state.setdefault("processed", 0)

    client = MicrotechGraphQLClientService()
    result = client.dataset_job(str(job.external_job_id))
    artikel_service = MicrotechArtikelService(erp=client)
    artikel_service.load_result(result)
    lager_service = MicrotechLagerService(erp=client)
    tax_map = SyncCommand._ensure_taxes()
    cmd = SyncCommand()
    admin_user_id = _get_admin_user_id()
    content_type_id = ContentType.objects.get_for_model(ProductModel).id if admin_user_id else None

    with TaskIssueCollector("products.scheduled_product_sync"), disable_product_auto_sync():
        while not artikel_service.range_eof():
            if limit and state["processed"] >= limit:
                break
            try:
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
            artikel_service.range_next()

    if mode == "selected":
        next_index = selected_index + 1
        if next_index < len(erp_nrs):
            logger.info(
                "scheduled_product_sync: next selected Microtech product {}/{} (processed={}, success={}, errors={})",
                next_index + 1,
                len(erp_nrs),
                state["processed"],
                state["success"],
                state["errors"],
            )
            MicrotechJobSentinelService().submit_dataset_records(
                input_data=_build_product_dataset_input(
                    include_inactive=include_inactive,
                    include_images=include_images,
                    find_key=[erp_nrs[next_index]],
                ),
                continuation=PRODUCT_SYNC_CONTINUATION,
                context={
                    **context,
                    "selected_index": next_index,
                    "state": state,
                },
                next_step="Naechsten ausgewaehlten Artikel aus Microtech importieren.",
            )
            return

        logger.info(
            "scheduled_product_sync: selected Microtech import complete (count={}, processed={}, success={}, errors={}, include_images={})",
            len(erp_nrs),
            state["processed"],
            state["success"],
            state["errors"],
            include_images,
        )
        _finalize_scheduled_product_sync(include_images=include_images, erp_nrs=erp_nrs)
        return

    limit_reached = bool(limit and state["processed"] >= limit)
    if result.get("hasMore") and not limit_reached:
        logger.info(
            "scheduled_product_sync: next Microtech page (processed={}, success={}, errors={})",
            state["processed"],
            state["success"],
            state["errors"],
        )
        next_context = {
            **context,
            "state": state,
        }
        MicrotechJobSentinelService().submit_dataset_records(
            input_data=_build_product_dataset_input(
                include_inactive=include_inactive,
                include_images=include_images,
                after=result.get("nextCursor"),
            ),
            continuation=PRODUCT_SYNC_CONTINUATION,
            context=next_context,
            next_step="Naechste Produktseite aus Microtech importieren.",
        )
        return

    logger.info(
        "scheduled_product_sync: Microtech import complete (processed={}, success={}, errors={}, include_images={})",
        state["processed"],
        state["success"],
        state["errors"],
        include_images,
    )
    _finalize_scheduled_product_sync(include_images=include_images, limit=limit)


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


def register_product_sync_continuations() -> None:
    from microtech.services import register_continuation

    register_continuation(PRODUCT_SYNC_CONTINUATION, _scheduled_product_sync_continuation)


register_product_sync_continuations()
