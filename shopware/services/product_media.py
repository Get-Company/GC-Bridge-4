from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

from django.conf import settings
from loguru import logger

from core.services import BaseService

if TYPE_CHECKING:
    from products.models import Product
    from .product import ProductService


class ProductMediaSyncService(BaseService):
    def build_media_sync_hash(self, *, product: "Product") -> str:
        file_names: list[str] = []
        last_media_change = None

        for product_image in product.get_ordered_product_images():
            image = product_image.image
            if not image:
                continue

            file_names.append(image.filename or image.path or "")
            for candidate in (getattr(product_image, "updated_at", None), getattr(image, "updated_at", None)):
                if candidate and (last_media_change is None or candidate > last_media_change):
                    last_media_change = candidate

        fingerprint = "|".join(file_names)
        last_media_change_value = last_media_change.isoformat() if last_media_change else ""
        return hashlib.sha256(f"{fingerprint}::{last_media_change_value}".encode("utf-8")).hexdigest()

    @staticmethod
    def has_media_changed(*, product: "Product", media_sync_hash: str) -> bool:
        return (getattr(product, "shopware_image_sync_hash", "") or "") != media_sync_hash

    def get_product_media_payload(
        self,
        *,
        product: "Product",
        product_id: str,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        media_relations: list[dict] = []
        media_entities: dict[str, dict] = {}
        media_uploads: dict[str, dict] = {}

        for product_image in product.get_ordered_product_images():
            image = product_image.image
            if not image:
                continue

            media_id = self.build_media_id(image.path)
            media_entities.setdefault(media_id, self.build_media_entity_payload(media_id))
            media_uploads.setdefault(
                media_id,
                {
                    "media_id": media_id,
                    "file_name": image.filename,
                    "source_url": image.url,
                },
            )
            media_relations.append(
                {
                    "id": self.build_product_media_id(product_id=product_id, media_id=media_id),
                    "mediaId": media_id,
                    "position": product_image.order,
                }
            )

        return media_relations, list(media_entities.values()), list(media_uploads.values())

    def sync_media_assets(
        self,
        *,
        product_service: "ProductService",
        media_entities: list[dict],
        media_uploads: list[dict],
        log_uploads: bool = False,
    ) -> None:
        if media_entities:
            product_service.bulk_upsert_media(media_entities)
        for upload in media_uploads:
            if log_uploads:
                logger.info(
                    "Shopware image upload start: media_id={} file_name={} source_url={}",
                    upload["media_id"],
                    upload["file_name"],
                    upload["source_url"],
                )
            try:
                product_service.upload_media_from_url(
                    media_id=upload["media_id"],
                    file_name=upload["file_name"],
                    source_url=upload["source_url"],
                )
            except Exception:
                if log_uploads:
                    logger.exception(
                        "Shopware image upload failed: media_id={} file_name={}",
                        upload["media_id"],
                        upload["file_name"],
                    )
                raise
            if log_uploads:
                logger.info(
                    "Shopware image upload ok: media_id={} file_name={}",
                    upload["media_id"],
                    upload["file_name"],
                )

    @staticmethod
    def build_media_id(file_name: str) -> str:
        return hashlib.md5(f"product-media:{file_name}".encode("utf-8")).hexdigest()

    @staticmethod
    def build_product_media_id(*, product_id: str, media_id: str) -> str:
        return hashlib.md5(f"{product_id}:{media_id}".encode("utf-8")).hexdigest()

    @staticmethod
    def build_media_entity_payload(media_id: str) -> dict:
        payload = {"id": media_id}
        media_folder_id = str(getattr(settings, "SHOPWARE_PRODUCT_MEDIA_FOLDER_ID", "")).strip()
        if media_folder_id:
            payload["mediaFolderId"] = media_folder_id
        return payload

    @staticmethod
    def split_file_name(file_name: str) -> tuple[str, str]:
        base_name, extension = os.path.splitext(file_name)
        if not base_name or not extension:
            raise ValueError(f"Bilddatei '{file_name}' hat keine gueltige Dateiendung.")
        return base_name, extension.lstrip(".").lower()
