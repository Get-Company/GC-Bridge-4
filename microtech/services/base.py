from __future__ import annotations

import re
from typing import Any

from loguru import logger

from core.services import BaseService
from microtech.services.graphql_client import MicrotechGraphQLClientService


class MicrotechGraphQLDatasetUnsupported(RuntimeError):
    pass


class MicrotechDatasetService(BaseService):
    dataset_name: str | None = None
    index_field: str | None = None
    default_fields: tuple[str, ...] = ()
    page_limit: int = 500

    def __init__(
        self,
        *,
        erp: Any,
        dataset_name: str | None = None,
        index_field: str | None = None,
        dataset: Any | None = None,
    ) -> None:
        self.client = erp if isinstance(erp, MicrotechGraphQLClientService) else MicrotechGraphQLClientService()
        self.dataset_name = dataset_name or self.dataset_name
        self.index_field = index_field or self.index_field
        if not self.dataset_name:
            raise ValueError("dataset_name is required for Microtech datasets.")
        self.dataset = dataset
        self._records: list[dict[str, Any]] = []
        self._cursor = 0
        self._loaded = False
        self._has_more = False
        self._next_cursor: list[Any] | None = None
        self._range: dict[str, Any] | None = None
        self._filter: str = ""
        self._last_result: dict[str, Any] = {}

    def find(self, search_value: Any, index_field: str | None = None) -> bool:
        index_field = index_field or self.index_field
        input_data = self._build_request(
            index_field=index_field,
            find_key=self._as_values(search_value),
            limit=1,
        )
        result = self.client.poll_dataset_records(input_data, timeout=60)
        self._load_result(result)
        logger.debug(
            "Dataset '{}' GraphQL FindKey({}, {}) -> {}",
            self.dataset_name,
            index_field,
            search_value,
            bool(self._records),
        )
        return bool(self._records)

    def get_field(self, field_name: str, *, silent: bool = False) -> Any:
        record = self._current_record()
        if record is None:
            if silent:
                return None
            logger.warning("Dataset '{}' has no current record for field '{}'.", self.dataset_name, field_name)
            return None
        return record.get(field_name)

    def set_range(self, from_range: Any, to_range: Any, *, field: str | None = None) -> bool:
        self._range = {
            "indexField": field or self.index_field,
            "fromValues": self._as_values(from_range),
            "toValues": self._as_values(to_range),
        }
        self._reset_records()
        return True

    def set_filter(self, filters: dict[str, Any]) -> bool:
        self._filter = " AND ".join(
            f"{field} = {self._format_filter_value(value)}"
            for field, value in (filters or {}).items()
        )
        self._reset_records()
        return True

    def clear_filter(self) -> bool:
        self._filter = ""
        self._reset_records()
        return True

    def is_ranged(self) -> bool:
        self._ensure_loaded()
        return bool(self._records)

    def range_first(self) -> None:
        self._ensure_loaded()
        self._cursor = 0

    def range_last(self) -> None:
        self._ensure_loaded()
        while self._has_more:
            self._fetch_next_page()
        self._cursor = max(0, len(self._records) - 1)

    def range_next(self) -> None:
        self._ensure_loaded()
        self._cursor += 1
        if self._cursor >= len(self._records) and self._has_more:
            self._fetch_next_page()

    def range_eof(self) -> bool:
        self._ensure_loaded()
        return self._cursor >= len(self._records)

    def range_count(self) -> int:
        self._ensure_loaded()
        return int(self._last_result.get("recordCount") or len(self._records))

    def get_field_img_filename(self, field_name: str) -> str | None:
        return self._find_image_filename_in_path(self.get_field(field_name, silent=True))

    def edit(self) -> None:
        raise MicrotechGraphQLDatasetUnsupported("Dataset edit is not available in GC-Bridge. Use GraphQL mutations.")

    def append(self) -> None:
        raise MicrotechGraphQLDatasetUnsupported("Dataset append is not available in GC-Bridge. Use GraphQL mutations.")

    def post(self) -> None:
        raise MicrotechGraphQLDatasetUnsupported("Dataset post is not available in GC-Bridge. Use GraphQL mutations.")

    def cancel(self) -> None:
        return None

    def delete(self) -> None:
        raise MicrotechGraphQLDatasetUnsupported("Dataset delete is not available in GC-Bridge. Use GraphQL mutations.")

    def set_field(self, field_name: str, value: Any) -> bool:
        raise MicrotechGraphQLDatasetUnsupported("Dataset field writes are not available in GC-Bridge. Use GraphQL mutations.")

    def get_special_object(self, special_object_name: str) -> Any | None:
        raise MicrotechGraphQLDatasetUnsupported(
            f"SpecialObject '{special_object_name}' is not available in GC-Bridge. Use GraphQL mutations."
        )

    def _build_request(
        self,
        *,
        index_field: str | None,
        find_key: list[Any] | None = None,
        after: list[Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        input_data: dict[str, Any] = {
            "dataset": self.dataset_name,
            "fields": list(self.default_fields),
            "limit": limit or self.page_limit,
        }
        if index_field:
            input_data["indexField"] = index_field
        if find_key is not None:
            input_data["findKey"] = find_key
            return input_data
        if not self._range:
            raise ValueError("Range is required for dataset page reads.")
        input_data["range"] = {
            "fromValues": self._range["fromValues"],
            "toValues": self._range["toValues"],
        }
        if self._range.get("indexField"):
            input_data["indexField"] = self._range["indexField"]
        if self._filter:
            input_data["filter"] = self._filter
        if after:
            input_data["after"] = after
        return input_data

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._range:
            self._records = []
            self._loaded = True
            return
        result = self.client.poll_dataset_records(self._build_request(index_field=self._range.get("indexField")))
        self._load_result(result)

    def _fetch_next_page(self) -> None:
        if not self._has_more or not self._next_cursor:
            return
        previous_len = len(self._records)
        result = self.client.poll_dataset_records(
            self._build_request(index_field=self._range.get("indexField"), after=self._next_cursor),
        )
        new_records = self._normalize_records(result.get("records") or [])
        self._records.extend(new_records)
        self._last_result = result
        self._has_more = bool(result.get("hasMore"))
        self._next_cursor = result.get("nextCursor")
        self._cursor = previous_len

    def _load_result(self, result: dict[str, Any]) -> None:
        self._records = self._normalize_records(result.get("records") or [])
        self._cursor = 0
        self._loaded = True
        self._last_result = result
        self._has_more = bool(result.get("hasMore"))
        self._next_cursor = result.get("nextCursor")

    def _reset_records(self) -> None:
        self._records = []
        self._cursor = 0
        self._loaded = False
        self._has_more = False
        self._next_cursor = None
        self._last_result = {}

    @staticmethod
    def _format_filter_value(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'"

    def _current_record(self) -> dict[str, Any] | None:
        self._ensure_loaded()
        if self._cursor < 0 or self._cursor >= len(self._records):
            return None
        return self._records[self._cursor]

    @staticmethod
    def _normalize_records(records: Any) -> list[dict[str, Any]]:
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)]

    @staticmethod
    def _as_values(value: Any) -> list[Any]:
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]

    @staticmethod
    def _find_image_filename_in_path(image_link_or_path: str | None) -> str | None:
        if not image_link_or_path:
            return None
        cleaned = str(image_link_or_path).split("?", 1)[0].split("#", 1)[0].strip().strip('"').strip("'")
        filename = cleaned.replace("\\", "/").rstrip("/").split("/")[-1]
        if re.search(r"\.(jpg|jpeg|png|gif|webp)$", filename, re.IGNORECASE):
            return filename
        match = re.search(r"[^/\\\\]+\.(jpg|jpeg|png|gif|webp)", cleaned, re.IGNORECASE)
        if match:
            return match.group(0).replace("\\", "/").split("/")[-1]
        return None
