from __future__ import annotations

from typing import Any

from .product_media import ProductMediaSyncService
from shopware.services.shopware6 import Shopware6Service


class ProductService(Shopware6Service):
    resource = "product"
    base_path = "/product"
    search_path = "/search/product"
    product_price_search_path = "/search/product-price"
    product_price_base_path = "/product-price"
    product_media_search_path = "/search/product-media"
    product_media_base_path = "/product-media"
    media_base_path = "/media"
    bulk_sync_path = "/_action/sync"

    def get(self, product_id: str) -> Any:
        return self.request_get(f"{self.base_path}/{product_id}")

    def list(self, criteria: dict | Any | None = None) -> Any:
        payload = self._criteria_payload(criteria)
        return self.request_post(self.search_path, payload=payload)

    def get_by_number(self, product_number: str, *, limit: int = 1) -> Any:
        criteria = {
            "filter": [
                {
                    "type": "equals",
                    "field": "productNumber",
                    "value": product_number,
                }
            ],
            "limit": limit,
        }
        return self.request_post(self.search_path, payload=criteria)

    def get_sku_map(self, product_numbers: list[str]) -> dict[str, str]:
        normalized_numbers = sorted({str(value).strip() for value in (product_numbers or []) if str(value).strip()})
        if not normalized_numbers:
            return {}
        criteria = {
            "filter": [
                {
                    "type": "equalsAny",
                    "field": "productNumber",
                    "value": "|".join(normalized_numbers),
                }
            ],
            "limit": len(normalized_numbers),
        }
        result = self.request_post(self.search_path, payload=criteria)
        mapping = self._extract_sku_map(result)
        missing_numbers = [product_number for product_number in normalized_numbers if product_number not in mapping]
        for product_number in missing_numbers:
            resolved_sku = self.find_sku_by_number(product_number)
            if resolved_sku:
                mapping[product_number] = resolved_sku
        return mapping

    def find_sku_by_number(self, product_number: str) -> str:
        product_number = str(product_number).strip()
        if not product_number:
            return ""
        result = self.get_by_number(product_number, limit=1)
        mapping = self._extract_sku_map(result)
        return mapping.get(product_number, "")

    def bulk_upsert(self, payload: list[dict], *, entity_name: str = "product") -> Any:
        if not payload:
            return None
        sync_payload = {
            f"{entity_name}-bulk": {
                "entity": entity_name,
                "action": "upsert",
                "payload": payload,
            }
        }
        return self.request_post(self.bulk_sync_path, payload=sync_payload)

    def bulk_upsert_media(self, payload: list[dict]) -> Any:
        return self.bulk_upsert(payload, entity_name="media")

    def purge_product_prices_by_product_and_rule(self, *, product_ids: list[str], rule_ids: list[str]) -> int:
        product_ids = [str(value).strip() for value in (product_ids or []) if str(value).strip()]
        rule_ids = [str(value).strip() for value in (rule_ids or []) if str(value).strip()]
        if not product_ids or not rule_ids:
            return 0

        product_values = "|".join(sorted(set(product_ids)))
        rule_values = "|".join(sorted(set(rule_ids)))
        page = 1
        limit = 500
        price_ids: list[str] = []

        while True:
            payload = {
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "productId",
                        "value": product_values,
                    },
                    {
                        "type": "equalsAny",
                        "field": "ruleId",
                        "value": rule_values,
                    },
                ],
                "limit": limit,
                "page": page,
            }
            result = self.request_post(self.product_price_search_path, payload=payload)
            rows = (result or {}).get("data", []) or []
            if not rows:
                break

            for row in rows:
                row_id = self._entity_id(row)
                if row_id:
                    price_ids.append(row_id)

            if len(rows) < limit:
                break
            page += 1

        for price_id in sorted(set(price_ids)):
            self.request_delete(f"{self.product_price_base_path}/{price_id}")

        return len(set(price_ids))

    def purge_product_media_by_product_ids(self, *, product_ids: list[str]) -> int:
        product_ids = [str(value).strip() for value in (product_ids or []) if str(value).strip()]
        if not product_ids:
            return 0

        product_values = "|".join(sorted(set(product_ids)))
        page = 1
        limit = 500
        product_media_ids: list[str] = []

        while True:
            payload = {
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "productId",
                        "value": product_values,
                    }
                ],
                "limit": limit,
                "page": page,
            }
            result = self.request_post(self.product_media_search_path, payload=payload)
            rows = (result or {}).get("data", []) or []
            if not rows:
                break

            for row in rows:
                row_id = self._entity_id(row)
                if row_id:
                    product_media_ids.append(row_id)

            if len(rows) < limit:
                break
            page += 1

        for product_media_id in sorted(set(product_media_ids)):
            self.request_delete(f"{self.product_media_base_path}/{product_media_id}")

        return len(set(product_media_ids))

    def find_media_ids_by_filename(
        self,
        *,
        file_name: str,
        extension: str,
    ) -> list[str]:
        payload = {
            "filter": [
                {
                    "type": "equals",
                    "field": "fileName",
                    "value": file_name,
                },
                {
                    "type": "equals",
                    "field": "fileExtension",
                    "value": extension,
                },
            ],
            "limit": 50,
        }
        result = self.request_post("/search/media", payload=payload)
        return [
            media_id
            for media_id in (self._entity_id(row) for row in (result or {}).get("data", []))
            if media_id
        ]

    def delete_media_by_ids(self, media_ids: list[str]) -> int:
        deleted = 0
        for media_id in sorted({str(value).strip() for value in media_ids if str(value).strip()}):
            self.request_delete(f"{self.media_base_path}/{media_id}")
            deleted += 1
        return deleted

    def delete_conflicting_media_by_filename(
        self,
        *,
        file_name: str,
        extension: str,
        exclude_media_id: str,
    ) -> int:
        media_ids = [
            media_id
            for media_id in self.find_media_ids_by_filename(file_name=file_name, extension=extension)
            if media_id != exclude_media_id
        ]
        return self.delete_media_by_ids(media_ids)

    def upload_media_from_url(self, *, media_id: str, file_name: str, source_url: str) -> Any:
        base_name, extension = ProductMediaSyncService.split_file_name(file_name)
        self.delete_conflicting_media_by_filename(
            file_name=base_name,
            extension=extension,
            exclude_media_id=media_id,
        )
        try:
            return self.request_post(
                f"/_action/media/{media_id}/upload",
                payload={"url": source_url},
                additional_query_params={
                    "extension": extension,
                    "fileName": base_name,
                },
            )
        except RuntimeError as exc:
            if not self._is_duplicate_media_filename_error(exc):
                raise
            self.delete_conflicting_media_by_filename(
                file_name=base_name,
                extension=extension,
                exclude_media_id=media_id,
            )
            return self.request_post(
                f"/_action/media/{media_id}/upload",
                payload={"url": source_url},
                additional_query_params={
                    "extension": extension,
                    "fileName": base_name,
                },
            )

    def create(self, payload: dict) -> Any:
        return self.request_post(self.base_path, payload=payload)

    def update(self, product_id: str, payload: dict) -> Any:
        return self.request_patch(f"{self.base_path}/{product_id}", payload=payload)

    def delete(self, product_id: str) -> Any:
        return self.request_delete(f"{self.base_path}/{product_id}")

    @staticmethod
    def _criteria_payload(criteria: dict | Any | None) -> dict:
        if criteria is None:
            return {}
        if isinstance(criteria, dict):
            return criteria
        if hasattr(criteria, "to_dict"):
            return criteria.to_dict()
        raise TypeError("criteria must be a dict or an object with to_dict().")

    @staticmethod
    def _entity_id(row: dict[str, Any]) -> str:
        if not isinstance(row, dict):
            return ""
        row_id = row.get("id")
        if row_id:
            return str(row_id).strip()
        attributes = row.get("attributes") or {}
        if isinstance(attributes, dict) and attributes.get("id"):
            return str(attributes["id"]).strip()
        return ""

    @classmethod
    def _extract_product_number(cls, row: dict[str, Any]) -> str:
        if not isinstance(row, dict):
            return ""
        product_number = row.get("productNumber")
        if product_number:
            return str(product_number).strip()
        attributes = row.get("attributes") or {}
        if isinstance(attributes, dict) and attributes.get("productNumber"):
            return str(attributes["productNumber"]).strip()
        return ""

    @classmethod
    def _extract_sku_map(cls, result: Any) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for item in (result or {}).get("data", []):
            product_number = cls._extract_product_number(item)
            sku = cls._entity_id(item)
            if product_number and sku:
                mapping[product_number] = sku
        return mapping

    @staticmethod
    def _is_duplicate_media_filename_error(exc: Exception) -> bool:
        message = str(exc)
        return "CONTENT__MEDIA_DUPLICATED_FILE_NAME" in message


__all__ = ["ProductService"]
