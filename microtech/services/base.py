from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from loguru import logger

from core.services import BaseService

try:
    import pywintypes
    COM_ERROR = pywintypes.com_error
except ImportError:  # pragma: no cover
    COM_ERROR = Exception


class MicrotechDatasetService(BaseService):
    dataset_name: str | None = None
    index_field: str | None = None

    def __init__(
        self,
        *,
        erp: Any,
        dataset_name: str | None = None,
        index_field: str | None = None,
        dataset: Any | None = None,
    ) -> None:
        self.erp = erp
        self.dataset_name = dataset_name or self.dataset_name
        self.index_field = index_field or self.index_field
        if not self.dataset_name:
            raise ValueError("dataset_name is required for Microtech datasets.")
        if not self.index_field:
            raise ValueError("index_field is required for Microtech datasets.")
        self.dataset = dataset or self._create_dataset()

    def _create_dataset(self) -> Any:
        if not self.erp:
            raise ValueError("An active ERP connection is required.")
        try:
            return self.erp.DataSetInfos.Item(self.dataset_name).CreateDataSet()
        except COM_ERROR as exc:
            logger.error("Failed to create dataset '{}': {}", self.dataset_name, exc)
            raise

    def _require_dataset(self) -> None:
        if self.dataset is None:
            raise ValueError(f"Kein Dataset geladen für {self.dataset_name}.")

    def find(self, search_value: Any, index_field: str | None = None) -> bool:
        self._require_dataset()
        index_field = index_field or self.index_field
        try:
            found = bool(self.dataset.FindKey(index_field, search_value))
            logger.debug(
                "Dataset '{}' FindKey({}, {}) -> {}",
                self.dataset_name,
                index_field,
                search_value,
                found,
            )
            return found
        except COM_ERROR as exc:
            logger.error(
                "Error finding record in '{}' with {} = '{}': {}",
                self.dataset_name,
                index_field,
                search_value,
                exc,
            )
            return False

    def _read_field(self, field: Any) -> Any:
        field_type_map = {
            "WideString": "AsString",
            "String": "AsString",
            "Double": "AsString",
            "Float": "AsFloat",
            "Blob": "Text",
            "Info": "Text",
            "Date": "AsDatetime",
            "DateTime": "AsDatetime",
            "Integer": "AsInteger",
            "Boolean": "AsInteger",
            "Byte": "AsInteger",
            "AutoInc": "AsInteger",
        }
        cast_type = field_type_map.get(field.FieldType)
        if not cast_type:
            logger.warning("Unknown FieldType: {}", field.FieldType)
            return None
        try:
            return getattr(field, cast_type)
        except AttributeError:
            logger.error("Field missing attribute '{}'.", cast_type)
            return None
        except Exception as exc:
            logger.error("Error while casting field: {}", exc)
            return None

    def get_field(self, field_name: str) -> Any:
        self._require_dataset()
        try:
            field = self.dataset.Fields(field_name)
            return self._read_field(field)
        except COM_ERROR as exc:
            logger.error("Error reading field '{}': {}", field_name, exc)
            return None

    def set_field(self, field_name: str, value: Any) -> bool:
        self._require_dataset()
        if value is None:
            logger.debug("Value for field '{}' is None. Skipping.", field_name)
            return True

        try:
            field = self.dataset.Fields.Item(field_name)
            field_type_map = {
                "WideString": "AsString",
                "String": "AsString",
                "Double": "AsString",
                "Float": "AsFloat",
                "Blob": "Text",
                "Info": "Text",
                "Date": "AsString",
                "DateTime": "AsString",
                "Integer": "AsInteger",
                "Boolean": "AsInteger",
                "Byte": "AsInteger",
            }
            cast_type = field_type_map.get(field.FieldType)
            if not cast_type:
                logger.warning("Unknown FieldType for writing: {}", field.FieldType)
                return False

            if isinstance(value, bool):
                value = 1 if value else 0
            elif isinstance(value, datetime):
                value = value.strftime("%d.%m.%Y %H:%M:%S.%f")
            elif isinstance(value, date):
                value = value.strftime("%d.%m.%Y")

            setattr(field, cast_type, value)
            logger.debug(
                "Value '{}' set in field '{}' of dataset '{}'.",
                value,
                field_name,
                self.dataset_name,
            )
            return True
        except COM_ERROR as exc:
            logger.error("Error writing to field '{}' with value '{}': {}", field_name, value, exc)
            return False
        except Exception as exc:
            logger.error("Unexpected error setting field '{}': {}", field_name, exc)
            return False

    def get_special_object(self, special_object_name: str) -> Any | None:
        special_objects = {
            "soLager": 0,
            "soVorgang": 1,
            "soDokumente": 2,
            "soKontenAnalyse": 3,
            "soAppObject": 4,
            "soWandeln": 5,
            "soDoublette": 6,
            "soEvents": 7,
            "soNachricht": 8,
            "soVariablen": 9,
            "soDrucken": 10,
            "soBanking": 11,
            "soBuchungen": 12,
            "soEBilanz": 13,
            "soOffenePosten": 14,
            "soZahlungsverkehr": 15,
            "soAusgabeVerzeichnis": 16,
            "soTableDefinition": 17,
            "soAdrSpezPr": 18,
            "soModificationMonitor": 19,
            "soProjekte": 20,
        }
        obj_code = special_objects.get(special_object_name)
        if obj_code is None:
            return None
        return self.erp.GetSpecialObject(obj_code)

    def get_field_img_filename(self, field_name: str) -> str | None:
        self._require_dataset()
        try:
            link_filename = self.dataset.Fields.Item(field_name).GetEditObject(4).LinkFileName
            return self._find_image_filename_in_path(link_filename)
        except COM_ERROR as exc:
            logger.error("Error getting image filename from field '{}': {}", field_name, exc)
            return None

    @staticmethod
    def _find_image_filename_in_path(image_link_or_path: str | None) -> str | None:
        if not image_link_or_path:
            return None
        match = re.search(r"[\w-]+\.(jpg|jpeg|png|gif|webp)", image_link_or_path, re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    def edit(self) -> None:
        self._require_dataset()
        try:
            self.dataset.Edit()
            logger.debug("Dataset '{}' is in edit mode.", self.dataset_name)
        except COM_ERROR as exc:
            logger.error("Error entering edit mode for dataset '{}': {}", self.dataset_name, exc)

    def append(self) -> None:
        self._require_dataset()
        try:
            self.dataset.Append()
            logger.debug("Append on dataset '{}'.", self.dataset_name)
        except COM_ERROR as exc:
            logger.error("Error appending to dataset '{}': {}", self.dataset_name, exc)

    def post(self) -> None:
        self._require_dataset()
        try:
            self.dataset.Post()
            logger.debug("Posted changes to dataset '{}'.", self.dataset_name)
        except COM_ERROR as exc:
            logger.error("Error posting changes to dataset '{}': {}", self.dataset_name, exc)
            self.cancel()

    def cancel(self) -> None:
        self._require_dataset()
        try:
            self.dataset.Cancel()
            logger.debug("Canceled changes to dataset '{}'.", self.dataset_name)
        except COM_ERROR as exc:
            logger.error("Error canceling changes to dataset '{}': {}", self.dataset_name, exc)

    def delete(self) -> None:
        self._require_dataset()
        try:
            if self.dataset.CheckDelete(False, True):
                self.dataset.Delete()
                logger.debug("Record deleted successfully.")
            else:
                logger.warning("Deletion canceled by ERP.")
        except COM_ERROR as exc:
            logger.error("Error deleting record: {}", exc)

    def set_range(self, from_range: Any, to_range: Any, *, field: str | None = None) -> bool:
        self._require_dataset()
        field = field or self.index_field
        self.dataset.SetRange(field, from_range, to_range)
        self.dataset.ApplyRange()
        if self.is_ranged():
            self.dataset.First()
            return True
        logger.warning("Dataset '{}' is not ranged.", self.dataset_name)
        return False

    def is_ranged(self) -> bool:
        self._require_dataset()
        return self.dataset.RecordCount > 0

    def range_first(self) -> None:
        self._require_dataset()
        self.dataset.First()

    def range_last(self) -> None:
        self._require_dataset()
        self.dataset.Last()

    def range_next(self) -> None:
        self._require_dataset()
        self.dataset.Next()

    def range_eof(self) -> bool:
        self._require_dataset()
        return self.dataset.Eof

    def range_count(self) -> int:
        self._require_dataset()
        return self.dataset.RecordCount

    def set_filter(self, filters: dict[str, Any]) -> bool:
        self._require_dataset()
        filter_parts = []
        for field, value in filters.items():
            if isinstance(value, str):
                filter_parts.append(f"[{field}] = '{value}'")
            else:
                filter_parts.append(f"[{field}] = {value}")

        filter_expression = " AND ".join(filter_parts)
        try:
            self.dataset.Filter = filter_expression
            self.dataset.Filtered = True
            logger.info("Filter applied to dataset '{}': {}", self.dataset_name, filter_expression)
            return True
        except COM_ERROR as exc:
            logger.error("Error applying filter to dataset '{}': {}", self.dataset_name, exc)
            return False

    def clear_filter(self) -> bool:
        self._require_dataset()
        try:
            self.dataset.Filtered = False
            self.dataset.Filter = ""
            logger.info("Filter cleared for dataset '{}'.", self.dataset_name)
            return True
        except COM_ERROR as exc:
            logger.error("Error clearing filter for dataset '{}': {}", self.dataset_name, exc)
            return False

    def is_filtered(self) -> bool:
        self._require_dataset()
        return bool(self.dataset.Filtered)
