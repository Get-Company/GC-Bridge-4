from __future__ import annotations

import hashlib
import json
from decimal import Decimal
import sys

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch
from loguru import logger
from core.admin_utils import log_admin_change
from core.services import CommandRuntimeService
from products.models import Price, Product, ProductImage, Storage
from shopware.models import ShopwareSettings
from shopware.services import ProductMediaSyncService, ProductService

DEFAULT_TAX_ID = "d391e13bdd95404a885f4ad28ea218e0"
REDUCED_TAX_ID = "be66a53eae3a49829f4a8c5959535501"


def _get_admin_user_id() -> int | None:
    user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
    return user.id if user else None


def _log_admin_error(
    *,
    admin_user_id: int | None,
    content_type_id: int | None,
    message: str,
    object_id: str | None = None,
    object_repr: str = "Shopware Sync",
) -> None:
    if not admin_user_id or not content_type_id:
        return
    log_admin_change(
        user_id=admin_user_id,
        content_type_id=content_type_id,
        object_id=object_id,
        object_repr=object_repr[:200],
        message=message,
    )


def _price_id(product_id: str, rule_id: str, suffix: str) -> str:
    return hashlib.md5(f"{product_id}-{rule_id}-{suffix}".encode("utf-8")).hexdigest()


def _build_standard_price(price: Price, currency_id: str) -> dict:
    return {
        "currencyId": currency_id,
        "gross": price.get_standard_brutto_price(as_float=True),
        "net": price.get_standard_price(as_float=True),
        "linked": True,
    }


def _build_base_price(price: Price, currency_id: str, rule_id: str) -> list[dict]:
    price_payload = {
        "currencyId": currency_id,
        "gross": price.get_current_brutto_price(as_float=True),
        "net": price.get_current_price(as_float=True),
        "linked": True,
        "isSpecialActive": price.is_special_active,
        "ruleId": rule_id,
    }
    if price.is_special_active:
        price_payload["listPrice"] = _build_standard_price(price, currency_id)
    return [price_payload]


def _build_prices_for_channel(product: Product, channel: ShopwareSettings, price: Price) -> list[dict]:
    rule_id = channel.rule_id_price
    currency_id = channel.currency_id
    if not rule_id or not currency_id:
        return []

    standard_price = _build_standard_price(price, currency_id)

    if price.is_special_active:
        return [
            {
                "id": _price_id(product.sku, rule_id, "special"),
                "productId": product.sku,
                "ruleId": rule_id,
                "quantityStart": 1,
                "quantityEnd": None,
                "price": [
                    {
                        "currencyId": currency_id,
                        "gross": price.get_special_brutto_price(as_float=True),
                        "net": price.get_special_price(as_float=True),
                        "linked": True,
                        "listPrice": standard_price,
                    }
                ],
            }
        ]

    if price.rebate_price and price.rebate_quantity:
        if price.rebate_quantity <= 1:
            return [
                {
                    "id": _price_id(product.sku, rule_id, "rebate"),
                    "productId": product.sku,
                    "ruleId": rule_id,
                    "quantityStart": 1,
                    "quantityEnd": None,
                    "price": [
                        {
                            "currencyId": currency_id,
                            "gross": price.get_rebate_brutto_price(as_float=True),
                            "net": price.get_rebate_price(as_float=True),
                            "linked": True,
                        }
                    ],
                }
            ]

        return [
            {
                "id": _price_id(product.sku, rule_id, "standard"),
                "productId": product.sku,
                "ruleId": rule_id,
                "quantityStart": 1,
                "quantityEnd": price.rebate_quantity - 1,
                "price": [standard_price],
            },
            {
                "id": _price_id(product.sku, rule_id, f"rebate-{price.rebate_quantity}"),
                "productId": product.sku,
                "ruleId": rule_id,
                "quantityStart": price.rebate_quantity,
                "quantityEnd": None,
                "price": [
                    {
                        "currencyId": currency_id,
                        "gross": price.get_rebate_brutto_price(as_float=True),
                        "net": price.get_rebate_price(as_float=True),
                        "linked": True,
                    }
                ],
            },
        ]

    return [
        {
            "id": _price_id(product.sku, rule_id, "standard"),
            "productId": product.sku,
            "ruleId": rule_id,
            "quantityStart": 1,
            "quantityEnd": None,
            "price": [standard_price],
        }
    ]


def _resolve_tax_id(product: Product) -> str:
    tax = getattr(product, "tax", None)
    if tax and tax.shopware_id:
        return str(tax.shopware_id).strip()
    if tax and tax.rate is not None and Decimal(tax.rate).quantize(Decimal("0.01")) == Decimal("7.00"):
        return REDUCED_TAX_ID
    return DEFAULT_TAX_ID


def _prefetch_sync_queryset(products):
    if hasattr(products, "select_related"):
        products = products.select_related("tax")
    if hasattr(products, "prefetch_related"):
        products = products.prefetch_related(
            Prefetch(
                "product_images",
                queryset=ProductImage.objects.select_related("image").order_by("order", "id"),
                to_attr="ordered_product_images",
            )
        )
    if hasattr(products, "only"):
        products = products.only(
            "id",
            "erp_nr",
            "sku",
            "name",
            "description",
            "is_active",
            "shopware_image_sync_hash",
            "tax_id",
            "tax__shopware_id",
        )
    return products


def _append_media_payload(
    *,
    product: Product,
    effective_sku: str,
    payload: dict,
    media_sync_service: ProductMediaSyncService,
    media_entities: dict[str, dict],
    media_uploads: dict[str, dict],
) -> None:
    product_media, product_media_entities, product_media_uploads = media_sync_service.get_product_media_payload(
        product=product,
        product_id=effective_sku,
    )
    if product_media:
        payload["media"] = product_media
        payload["coverId"] = product_media[0]["id"]
    for entity in product_media_entities:
        media_entities[entity["id"]] = entity
    for upload in product_media_uploads:
        media_uploads[upload["media_id"]] = upload


def _image_names_for_product(product: Product) -> list[str]:
    result: list[str] = []
    for product_image in product.get_ordered_product_images():
        image = product_image.image
        if not image:
            continue
        result.append(image.filename or image.path)
    return result


class Command(BaseCommand):
    help = "Sync products from Django to Shopware6 (updates only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern (productNumber). Wenn leer, nutze --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Alle Produkte synchronisieren.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl zu synchronisierender Produkte.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Batch-Groesse fuer Shopware6 Sync (Default: 50).",
        )
        parser.add_argument(
            "--only-with-images",
            action="store_true",
            help="Nur Produkte mit mindestens einem Bild synchronisieren.",
        )
        parser.add_argument(
            "--log-images",
            action="store_true",
            help="Schreibt aussagekraeftige Batch- und Produktlogs fuer den Bild-Sync.",
        )

    def handle(self, *args, **options):
        erp_nrs = [nr.strip() for nr in options.get("erp_nrs") or [] if nr.strip()]
        sync_all = options.get("all", False)
        limit = options.get("limit")
        batch_size = options.get("batch_size") or 50
        only_with_images = options.get("only_with_images", False)
        log_images = options.get("log_images", False)

        runtime = CommandRuntimeService().start(
            command_name="shopware_sync_products",
            argv=sys.argv,
            metadata={
                "mode": "all" if sync_all else "selected",
                "limit": limit,
                "batch_size": batch_size,
                "only_with_images": only_with_images,
                "log_images": log_images,
            },
        )
        try:
            if not erp_nrs and not sync_all:
                raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

            qs = Product.objects.all() if sync_all else Product.objects.filter(erp_nr__in=erp_nrs)
            if only_with_images:
                qs = qs.filter(product_images__isnull=False).distinct()
            qs = _prefetch_sync_queryset(qs)
            if limit:
                qs = qs[:limit]

            service = ProductService()
            media_sync_service = ProductMediaSyncService()
            admin_user_id = _get_admin_user_id()
            content_type_id = ContentType.objects.get_for_model(Product).id if admin_user_id else None
            channels = list(ShopwareSettings.objects.filter(is_active=True))
            default_channel = next((ch for ch in channels if ch.is_default), None)

            products = list(qs)
            total_products = len(products)
            runtime.update(stage="prepare", total_products=total_products)
            for offset in range(0, total_products, batch_size):
                batch = products[offset : offset + batch_size]
                batch_no = (offset // batch_size) + 1
                runtime.update(
                    stage="sync_batch",
                    processed=offset,
                    total_products=total_products,
                    current_batch_size=len(batch),
                )
                if log_images:
                    logger.info(
                        "Shopware image sync batch {}/{} start: size={} products={}",
                        batch_no,
                        (total_products + batch_size - 1) // batch_size if total_products else 0,
                        len(batch),
                        [product.erp_nr for product in batch],
                    )
                missing = [p.erp_nr for p in batch if not p.sku]
                sku_map = service.get_sku_map(missing) if missing else {}

                payloads = []
                payload_products: list[Product] = []
                fallback_products: list[Product] = []
                fallback_payloads: list[dict] = []
                media_entities: dict[str, dict] = {}
                media_uploads: dict[str, dict] = {}
                media_sync_hashes: list[tuple[Product, str]] = []
                cleanup_media_product_ids: list[str] = []
                for product in batch:
                    effective_sku = product.sku
                    if not effective_sku:
                        resolved_sku = sku_map.get(product.erp_nr)
                        if resolved_sku:
                            effective_sku = resolved_sku
                            product.sku = resolved_sku
                            product.save(update_fields=["sku"])

                    prices_by_channel = {
                        price.sales_channel_id: price
                        for price in product.prices.select_related("sales_channel").all()
                        if price.sales_channel_id
                    }
                    payload = {
                        "productNumber": product.erp_nr,
                        "active": product.is_active,
                        "taxId": _resolve_tax_id(product),
                    }
                    if effective_sku:
                        payload["id"] = effective_sku
                    if product.name:
                        payload["name"] = product.name
                    if product.description is not None:
                        payload["description"] = product.description
                    try:
                        storage = product.storage
                    except Storage.DoesNotExist:
                        storage = None
                    if storage:
                        payload["stock"] = storage.get_stock

                    if default_channel:
                        default_price = prices_by_channel.get(default_channel.id)
                        if default_price:
                            if default_channel.currency_id and default_channel.rule_id_price:
                                payload["price"] = _build_base_price(
                                    default_price,
                                    default_channel.currency_id,
                                    default_channel.rule_id_price,
                                )
                            else:
                                _log_admin_error(
                                    admin_user_id=admin_user_id,
                                    content_type_id=content_type_id,
                                    message=(
                                        f"Sales-Channel {default_channel.name} fehlt currency_id oder rule_id_price. "
                                        "Preis-Update übersprungen."
                                    ),
                                    object_id=str(product.pk),
                                    object_repr=f"Product {product.erp_nr}",
                                )
                        else:
                            _log_admin_error(
                                admin_user_id=admin_user_id,
                                content_type_id=content_type_id,
                                message=f"Kein Preis für Default-Sales-Channel bei Produkt {product.erp_nr}.",
                                object_id=str(product.pk),
                                object_repr=f"Product {product.erp_nr}",
                            )

                    prices_payload = []
                    if effective_sku:
                        for channel in channels:
                            price = prices_by_channel.get(channel.id)
                            if not price:
                                _log_admin_error(
                                    admin_user_id=admin_user_id,
                                    content_type_id=content_type_id,
                                    message=f"Kein Preis für Sales-Channel {channel.name} bei Produkt {product.erp_nr}.",
                                    object_id=str(product.pk),
                                    object_repr=f"Product {product.erp_nr}",
                                )
                                continue
                            if not channel.rule_id_price or not channel.currency_id:
                                _log_admin_error(
                                    admin_user_id=admin_user_id,
                                    content_type_id=content_type_id,
                                    message=f"Sales-Channel {channel.name} fehlt rule_id_price oder currency_id.",
                                    object_id=str(product.pk),
                                    object_repr=f"Product {product.erp_nr}",
                                )
                                continue
                            prices_payload.extend(_build_prices_for_channel(product, channel, price))
                    elif channels:
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=(
                                f"Advanced prices for product {product.erp_nr} übersprungen, "
                                "da SKU im Fallback-Upsert noch nicht vorhanden war."
                            ),
                            object_id=str(product.pk),
                            object_repr=f"Product {product.erp_nr}",
                        )

                    if prices_payload:
                        payload["prices"] = prices_payload

                    if effective_sku:
                        image_names = _image_names_for_product(product)
                        media_sync_hash = media_sync_service.build_media_sync_hash(product=product)
                        media_changed = media_sync_service.has_media_changed(product=product, media_sync_hash=media_sync_hash)
                        if log_images:
                            logger.info(
                                "Shopware image sync product erp_nr={} sku={} image_count={} changed={} images={}",
                                product.erp_nr,
                                effective_sku,
                                len(image_names),
                                media_changed,
                                image_names,
                            )
                        if media_changed:
                            cleanup_media_product_ids.append(effective_sku)
                            media_sync_hashes.append((product, media_sync_hash))
                            _append_media_payload(
                                product=product,
                                effective_sku=effective_sku,
                                payload=payload,
                                media_sync_service=media_sync_service,
                                media_entities=media_entities,
                                media_uploads=media_uploads,
                            )
                        payloads.append(payload)
                        payload_products.append(product)
                        continue

                    fallback_products.append(product)
                    fallback_payloads.append(payload)

                if not payloads and not fallback_payloads:
                    continue

                try:
                    cleanup_product_ids = [str(payload.get("id")).strip() for payload in payloads if payload.get("id")]
                    cleanup_rule_ids = [str(channel.rule_id_price).strip() for channel in channels if channel.rule_id_price]
                    if cleanup_product_ids and cleanup_rule_ids:
                        service.purge_product_prices_by_product_and_rule(
                            product_ids=cleanup_product_ids,
                            rule_ids=cleanup_rule_ids,
                        )
                    if cleanup_media_product_ids:
                        if log_images:
                            logger.info(
                                "Shopware image sync batch {} cleanup existing media relations for products={}",
                                batch_no,
                                cleanup_media_product_ids,
                            )
                        service.purge_product_media_by_product_ids(product_ids=cleanup_media_product_ids)
                    if log_images and payloads:
                        media_product_payloads = [
                            {
                                "erp_nr": product.erp_nr,
                                "sku": payload.get("id"),
                                "images": _image_names_for_product(product),
                                "media_relations": [
                                    {
                                        "id": relation.get("id"),
                                        "mediaId": relation.get("mediaId"),
                                        "position": relation.get("position"),
                                    }
                                    for relation in (payload.get("media") or [])
                                ],
                                "coverId": payload.get("coverId"),
                            }
                            for product, payload in zip(payload_products, payloads, strict=False)
                            if payload.get("media")
                        ]
                        logger.info(
                            "Shopware image sync batch {} upload stage: uploads={} products_with_media={}",
                            batch_no,
                            len(media_uploads),
                            [item["erp_nr"] for item in media_product_payloads],
                        )
                        logger.info(
                            "Shopware image sync batch {} media payload summary={}",
                            batch_no,
                            json.dumps(media_product_payloads, ensure_ascii=True),
                        )
                    if payloads:
                        media_sync_service.sync_media_assets(
                            product_service=service,
                            media_entities=list(media_entities.values()),
                            media_uploads=list(media_uploads.values()),
                            log_uploads=log_images,
                        )
                        if log_images:
                            logger.info(
                                "Shopware image sync batch {} product upsert start: payload_products={} products_with_media={}",
                                batch_no,
                                [payload.get("productNumber") for payload in payloads],
                                [payload.get("productNumber") for payload in payloads if payload.get("media")],
                            )
                        service.bulk_upsert(payloads)
                        if log_images:
                            logger.info(
                                "Shopware image sync batch {} product upsert ok: payload_products={}",
                                batch_no,
                                [payload.get("productNumber") for payload in payloads],
                            )
                    for synced_product, media_sync_hash in media_sync_hashes:
                        synced_product.shopware_image_sync_hash = media_sync_hash
                        synced_product.save(update_fields=["shopware_image_sync_hash", "updated_at"])
                    if fallback_products:
                        try:
                            if log_images:
                                logger.info(
                                    "Shopware image sync fallback create batch {} start: payload_products={}",
                                    batch_no,
                                    [payload.get("productNumber") for payload in fallback_payloads],
                                )
                            service.bulk_upsert(fallback_payloads)
                            if log_images:
                                logger.info(
                                    "Shopware image sync fallback create batch {} ok: payload_products={}",
                                    batch_no,
                                    [payload.get("productNumber") for payload in fallback_payloads],
                                )
                        except Exception as exc:
                            if log_images:
                                logger.exception(
                                    "Shopware image sync fallback create batch {} failed: payload_products={}",
                                    batch_no,
                                    [payload.get("productNumber") for payload in fallback_payloads],
                                )
                            for product in fallback_products:
                                _log_admin_error(
                                    admin_user_id=admin_user_id,
                                    content_type_id=content_type_id,
                                    message=f"Shopware fallback create failed for {product.erp_nr}: {exc}",
                                    object_id=str(product.pk),
                                    object_repr=f"Product {product.erp_nr}",
                                )
                        refreshed_map = service.get_sku_map([product.erp_nr for product in fallback_products])
                        fallback_media_payloads: list[dict] = []
                        fallback_media_entities: dict[str, dict] = {}
                        fallback_media_uploads: dict[str, dict] = {}
                        fallback_media_sync_hashes: list[tuple[Product, str]] = []
                        resolved_fallback_ids: list[str] = []
                        for product in fallback_products:
                            resolved_sku = refreshed_map.get(product.erp_nr)
                            if resolved_sku:
                                product.sku = resolved_sku
                                product.save(update_fields=["sku"])
                                image_names = _image_names_for_product(product)
                                media_sync_hash = media_sync_service.build_media_sync_hash(product=product)
                                media_changed = media_sync_service.has_media_changed(
                                    product=product,
                                    media_sync_hash=media_sync_hash,
                                )
                                if log_images:
                                    logger.info(
                                        "Shopware image sync fallback product erp_nr={} sku={} image_count={} changed={} images={}",
                                        product.erp_nr,
                                        resolved_sku,
                                        len(image_names),
                                        media_changed,
                                        image_names,
                                    )
                                if media_changed:
                                    resolved_fallback_ids.append(resolved_sku)
                                    fallback_media_sync_hashes.append((product, media_sync_hash))
                                    fallback_payload = {"id": resolved_sku, "productNumber": product.erp_nr}
                                    _append_media_payload(
                                        product=product,
                                        effective_sku=resolved_sku,
                                        payload=fallback_payload,
                                        media_sync_service=media_sync_service,
                                        media_entities=fallback_media_entities,
                                        media_uploads=fallback_media_uploads,
                                    )
                                    fallback_media_payloads.append(fallback_payload)
                                continue
                            _log_admin_error(
                                admin_user_id=admin_user_id,
                                content_type_id=content_type_id,
                                message=(
                                    f"Shopware SKU konnte nach Fallback-Upsert nicht aufgeloest werden "
                                    f"fuer productNumber {product.erp_nr}."
                                ),
                                object_id=str(product.pk),
                                object_repr=f"Product {product.erp_nr}",
                            )
                        if resolved_fallback_ids:
                            if log_images:
                                logger.info(
                                    "Shopware image sync fallback batch {} cleanup existing media relations for products={}",
                                    batch_no,
                                    resolved_fallback_ids,
                                )
                            service.purge_product_media_by_product_ids(product_ids=resolved_fallback_ids)
                            media_sync_service.sync_media_assets(
                                product_service=service,
                                media_entities=list(fallback_media_entities.values()),
                                media_uploads=list(fallback_media_uploads.values()),
                                log_uploads=log_images,
                            )
                            if log_images:
                                logger.info(
                                    "Shopware image sync fallback batch {} product upsert start: payload_products={}",
                                    batch_no,
                                    [payload.get("productNumber") for payload in fallback_media_payloads],
                                )
                            service.bulk_upsert(fallback_media_payloads)
                            if log_images:
                                logger.info(
                                    "Shopware image sync fallback batch {} product upsert ok: payload_products={}",
                                    batch_no,
                                    [payload.get("productNumber") for payload in fallback_media_payloads],
                                )
                            for synced_product, media_sync_hash in fallback_media_sync_hashes:
                                synced_product.shopware_image_sync_hash = media_sync_hash
                                synced_product.save(update_fields=["shopware_image_sync_hash", "updated_at"])
                except Exception as exc:
                    if log_images:
                        logger.exception(
                            "Shopware image sync batch {} failed: payload_products={} products_with_media={} cleanup_media_products={}",
                            batch_no,
                            [payload.get("productNumber") for payload in payloads],
                            [payload.get("productNumber") for payload in payloads if payload.get("media")],
                            cleanup_media_product_ids,
                        )
                    for product in payload_products:
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=f"Shopware bulk sync failed for {product.erp_nr}: {exc}",
                            object_id=str(product.pk),
                            object_repr=f"Product {product.erp_nr}",
                        )
        finally:
            runtime.close()
