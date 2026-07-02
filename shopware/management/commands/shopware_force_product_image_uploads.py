from __future__ import annotations

from collections.abc import Iterable

from django.core.management.base import CommandError
from django.db.models import Prefetch
from loguru import logger

from core.management.base import MonitoredBaseCommand
from products.models import Product, ProductImage
from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService


DEFAULT_BATCH_SIZE = 10


def _clean_erp_nrs(values: Iterable[str] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def _chunked(items: list[Product], size: int) -> Iterable[list[Product]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _prefetch_products(queryset):
    return queryset.prefetch_related(
        Prefetch(
            "product_images",
            queryset=ProductImage.objects.select_related("image").order_by("order", "id"),
            to_attr="ordered_product_images",
        )
    )


def _image_names_for_product(product: Product) -> list[str]:
    result: list[str] = []
    for product_image in product.get_ordered_product_images():
        image = product_image.image
        if image:
            result.append(image.filename or image.path)
    return result


def _append_media_payload(
    *,
    product: Product,
    product_id: str,
    payload: dict,
    media_sync_service: ProductMediaSyncService,
    media_entities: dict[str, dict],
    media_uploads: dict[str, dict],
) -> str:
    media_sync_hash = media_sync_service.build_media_sync_hash(product=product)
    product_media, product_media_entities, product_media_uploads = media_sync_service.get_product_media_payload(
        product=product,
        product_id=product_id,
    )
    payload["media"] = product_media
    payload["coverId"] = product_media[0]["id"] if product_media else None

    for entity in product_media_entities:
        media_entities[entity["id"]] = entity
    for upload in product_media_uploads:
        media_uploads[upload["media_id"]] = upload

    return media_sync_hash


class Command(MonitoredBaseCommand):
    help = (
        "Loescht Shopware-Produktbilder und Produkt-Media-Zuordnungen in 10er-Batches, "
        "laedt die Bilder neu hoch und setzt die Zuordnung erneut."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern (productNumber). Wenn leer, werden alle Produkte verarbeitet.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Kompatibilitaetsoption; ohne ERP-Nummern werden immer alle Produkte verarbeitet.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optionales Limit fuer die Produktauswahl.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Batch-Groesse fuer den Bild-Workflow (Default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--only-with-images",
            action="store_true",
            help="Nur Produkte mit mindestens einem expliziten ProductImage verarbeiten.",
        )
        parser.add_argument(
            "--log-images",
            action="store_true",
            help="Aktiviert aussagekraeftige Batch- und Produktlogs fuer den Bild-Sync.",
        )

    def handle(self, *args, **options):
        erp_nrs = _clean_erp_nrs(options.get("erp_nrs"))
        limit = options.get("limit")
        batch_size = options.get("batch_size") or DEFAULT_BATCH_SIZE
        only_with_images = options.get("only_with_images", False)
        log_images = options.get("log_images", False)
        if batch_size <= 0:
            raise CommandError("Batch-Groesse muss groesser als 0 sein.")

        queryset = Product.objects.filter(erp_nr__in=erp_nrs) if erp_nrs else Product.objects.all()
        if only_with_images:
            queryset = queryset.filter(product_images__isnull=False).distinct()
        queryset = _prefetch_products(queryset.order_by("erp_nr", "id"))
        if limit:
            queryset = queryset[:limit]

        products = list(queryset)
        total_products = len(products)
        total_batches = (total_products + batch_size - 1) // batch_size if total_products else 0
        service = ProductService()
        media_sync_service = ProductMediaSyncService()
        errors: list[dict[str, object]] = []

        self.stdout.write(
            f"Starte Shopware Bild-Neuaufbau: {total_products} Produkt(e), Batch-Groesse {batch_size}."
        )

        for batch_no, batch in enumerate(_chunked(products, batch_size), start=1):
            batch_erp_nrs = [product.erp_nr for product in batch]
            logger.info(
                "Shopware force image batch {}/{} start: size={} products={}",
                batch_no,
                total_batches,
                len(batch),
                batch_erp_nrs,
            )

            missing_sku_products = [product for product in batch if not product.sku]
            sku_map = service.get_sku_map([product.erp_nr for product in missing_sku_products])

            payloads: list[dict] = []
            media_entities: dict[str, dict] = {}
            media_uploads: dict[str, dict] = {}
            media_sync_hashes: list[tuple[Product, str]] = []
            product_ids: list[str] = []

            for product in batch:
                effective_sku = product.sku or sku_map.get(product.erp_nr, "")
                if effective_sku and product.sku != effective_sku:
                    product.sku = effective_sku
                    product.save(update_fields=["sku"])

                if not effective_sku:
                    self._record_error(
                        errors=errors,
                        batch_no=batch_no,
                        step="sku_lookup",
                        products=[product.erp_nr],
                        exc=RuntimeError("Shopware Produkt-ID konnte nicht aufgeloest werden."),
                    )
                    continue

                payload = {"id": effective_sku, "productNumber": product.erp_nr}
                media_sync_hash = _append_media_payload(
                    product=product,
                    product_id=effective_sku,
                    payload=payload,
                    media_sync_service=media_sync_service,
                    media_entities=media_entities,
                    media_uploads=media_uploads,
                )
                payloads.append(payload)
                product_ids.append(effective_sku)
                media_sync_hashes.append((product, media_sync_hash))

                if log_images:
                    logger.info(
                        "Shopware force image product prepared: erp_nr={} sku={} image_count={} images={}",
                        product.erp_nr,
                        effective_sku,
                        len(_image_names_for_product(product)),
                        _image_names_for_product(product),
                    )

            if not product_ids:
                logger.warning("Shopware force image batch {} skipped: no resolvable Shopware product IDs.", batch_no)
                continue

            if not self._run_delete_step(
                service=service,
                batch_no=batch_no,
                products=batch_erp_nrs,
                product_ids=product_ids,
                errors=errors,
            ):
                continue

            if not self._run_upload_step(
                service=service,
                media_sync_service=media_sync_service,
                batch_no=batch_no,
                products=batch_erp_nrs,
                media_entities=list(media_entities.values()),
                media_uploads=list(media_uploads.values()),
                log_images=log_images,
                errors=errors,
            ):
                continue

            if not self._run_assignment_step(
                service=service,
                batch_no=batch_no,
                products=batch_erp_nrs,
                payloads=payloads,
                errors=errors,
            ):
                continue

            for synced_product, media_sync_hash in media_sync_hashes:
                synced_product.shopware_image_sync_hash = media_sync_hash
                synced_product.save(update_fields=["shopware_image_sync_hash", "updated_at"])

            logger.info("Shopware force image batch {}/{} ok: products={}", batch_no, total_batches, batch_erp_nrs)

        if errors:
            logger.error("Shopware force image upload finished with errors: {}", errors)
            raise CommandError(f"Shopware Bild-Neuaufbau mit {len(errors)} Fehler(n) abgeschlossen. Details im Log.")

        self.stdout.write(self.style.SUCCESS("Shopware Bild-Neuaufbau abgeschlossen."))

    def _run_delete_step(
        self,
        *,
        service: ProductService,
        batch_no: int,
        products: list[str],
        product_ids: list[str],
        errors: list[dict[str, object]],
    ) -> bool:
        try:
            deleted = service.purge_product_media_by_product_ids(product_ids=product_ids)
            logger.info(
                "Shopware force image batch {} delete ok: products={} product_media_deleted={}",
                batch_no,
                products,
                deleted,
            )
            return True
        except Exception as exc:
            self._record_error(errors=errors, batch_no=batch_no, step="delete", products=products, exc=exc)
            return False

    def _run_upload_step(
        self,
        *,
        service: ProductService,
        media_sync_service: ProductMediaSyncService,
        batch_no: int,
        products: list[str],
        media_entities: list[dict],
        media_uploads: list[dict],
        log_images: bool,
        errors: list[dict[str, object]],
    ) -> bool:
        try:
            media_sync_service.sync_media_assets(
                product_service=service,
                media_entities=media_entities,
                media_uploads=media_uploads,
                log_uploads=log_images,
            )
            logger.info(
                "Shopware force image batch {} upload ok: products={} uploads={}",
                batch_no,
                products,
                len(media_uploads),
            )
            return True
        except Exception as exc:
            self._record_error(errors=errors, batch_no=batch_no, step="upload", products=products, exc=exc)
            return False

    def _run_assignment_step(
        self,
        *,
        service: ProductService,
        batch_no: int,
        products: list[str],
        payloads: list[dict],
        errors: list[dict[str, object]],
    ) -> bool:
        try:
            service.bulk_upsert(payloads)
            logger.info(
                "Shopware force image batch {} assignment ok: products={} payloads={}",
                batch_no,
                products,
                len(payloads),
            )
            return True
        except Exception as exc:
            self._record_error(errors=errors, batch_no=batch_no, step="assignment", products=products, exc=exc)
            return False

    @staticmethod
    def _record_error(
        *,
        errors: list[dict[str, object]],
        batch_no: int,
        step: str,
        products: list[str],
        exc: Exception,
    ) -> None:
        error = {
            "batch": batch_no,
            "step": step,
            "products": products,
            "error": str(exc),
        }
        errors.append(error)
        logger.opt(exception=exc).error(
            "Shopware force image batch {} step {} failed: products={} error={}",
            batch_no,
            step,
            products,
            exc,
        )
