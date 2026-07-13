from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import MicrotechDatasetService


class MicrotechArtikelService(MicrotechDatasetService):
    dataset_name = "Artikel"
    index_field = "Nr"
    default_fields = (
        "Nr",
        "ArtNr",
        "KuBez5",
        "Bez5",
        "Bez2",
        "WShopKz",
        "Sel6",
        "Einh",
        "Sel10",
        "Sel11",
        "Sel19",
        "Vk0.Preis",
        "Vk0.Rab0.Mge",
        "Vk0.Rab0.Pr",
        "Vk0.SPr",
        "Vk0.SVonDat",
        "Vk0.SBisDat",
        "StSchl",
        "StSchlSz",
        "Bez3",
        "Bild",
        "Bild2",
        "Bild3",
        "Bild4",
        "Bild5",
    )

    PRODUCT_IMAGE_FIELDS = ("Bild", "Bild2", "Bild3", "Bild4", "Bild5")

    def find(self, search_value: Any, index_field: str | None = None) -> bool:
        erp_number = self._first_value(search_value)
        if index_field and index_field not in {self.index_field, "ArtNr", "Nr", "erpNumber"}:
            return super().find(search_value, index_field=index_field)
        if not erp_number:
            self._load_product_record(None)
            return False

        result = self.client.request_product(str(erp_number).strip())
        product = result.get("product") if isinstance(result, dict) else None
        self._load_product_record(product)
        return bool(self._records)

    def load_product_record(self, product: dict[str, Any] | None) -> None:
        self._load_product_record(product)

    def set_range_all(self) -> bool:
        return self.set_range(from_range="00000000", to_range="99999999", field=self.index_field)

    def get_erp_nr(self):
        return self.get_field("ArtNr")

    def get_name(self):
        return self.get_field("KuBez5")

    def get_description(self):
        return self.get_field("Bez5")

    def get_description_short(self):
        return self.get_field("Bez2")

    def get_is_active(self):
        return self.get_field("WShopKz")

    def get_factor(self):
        factor = self.get_field("Sel6")
        if not factor:
            return None
        try:
            return float(factor)
        except (ValueError, TypeError):
            return None

    def get_unit(self, raw: bool = False):
        unit = self.get_field("Einh")
        if unit is None:
            return ""
        if not raw:
            unit = unit.replace("% ", "")
        return unit

    def get_min_purchase(self):
        return self.get_field("Sel10")

    def get_purchase_unit(self):
        return self.get_field("Sel11")

    def get_sort_order(self):
        return self.get_field("Sel19")

    def get_stock(self):
        return self.get_field("stock", silent=True)

    def get_storage_location(self):
        return self.get_field("storageLocation", silent=True)

    def get_warehouse_number(self) -> int | None:
        value = self.get_field("warehouseNumber", silent=True)
        try:
            warehouse_number = int(value)
        except (TypeError, ValueError):
            return None
        return warehouse_number if warehouse_number > 0 else None

    def get_price(self):
        return self.get_field("Vk0.Preis")

    def get_rebate_quantity(self):
        return self.get_field("Vk0.Rab0.Mge")

    def get_rebate_price(self):
        return self.get_field("Vk0.Rab0.Pr")

    def get_special_price(self):
        return self.get_field("Vk0.SPr")

    def get_special_start_date(self):
        return self.get_field("Vk0.SVonDat")

    def get_special_end_date(self):
        return self.get_field("Vk0.SBisDat")

    def get_image_list(self):
        return [
            img
            for img in (self.get_field_img_filename(field) for field in self.PRODUCT_IMAGE_FIELDS)
            if img
        ]

    def get_tax_key(self) -> str:
        return str(self.get_field("StSchl") or "").strip()

    def get_tax_rate(self) -> Decimal | None:
        direct_rate = self._parse_tax_rate(self.get_field("StSchlSz", silent=True))
        if direct_rate is not None:
            return direct_rate

        key = self.get_tax_key().upper().replace(" ", "")
        if "M7" in key:
            return Decimal("7.00")
        if "M19" in key:
            return Decimal("19.00")

        return None

    def get_bez3(self) -> str:
        return self.get_field("Bez3") or ""

    def get_customs_tariff_number(self) -> str:
        direct_value = str(self.get_field("customsTariffNumber", silent=True) or "").strip()
        if direct_value:
            return direct_value
        match = re.search(r"stat\.Warennr\.?\s*(\d+)", self.get_bez3())
        return match.group(1) if match else ""

    def get_weight_gross(self) -> Decimal | None:
        direct_value = self._to_decimal(self.get_field("weightGrossKg", silent=True))
        if direct_value is not None:
            return direct_value
        return self._parse_weight(self.get_bez3(), "brutto")

    def get_weight_net(self) -> Decimal | None:
        direct_value = self._to_decimal(self.get_field("weightNetKg", silent=True))
        if direct_value is not None:
            return direct_value
        return self._parse_weight(self.get_bez3(), "netto")

    def _load_product_record(self, product: dict[str, Any] | None) -> None:
        self._records = []
        self._cursor = 0
        self._loaded = True
        self._has_more = False
        self._next_cursor = None
        self._last_result = {}
        if not isinstance(product, dict) or product.get("deleted"):
            return

        images = self._normalize_images(product.get("images"))
        record: dict[str, Any] = {
            "Nr": product.get("erpNumber"),
            "ArtNr": product.get("erpNumber"),
            "KuBez5": product.get("name"),
            "Bez5": product.get("description"),
            "Bez2": product.get("descriptionShort"),
            "WShopKz": product.get("isActive"),
            "Sel6": product.get("factor"),
            "Einh": product.get("unit"),
            "Sel10": product.get("minPurchase"),
            "Sel11": product.get("purchaseUnit"),
            "Sel19": product.get("sortOrder"),
            "Vk0.Preis": product.get("price"),
            "Vk0.Rab0.Mge": product.get("rebateQuantity"),
            "Vk0.Rab0.Pr": product.get("rebatePrice"),
            "Vk0.SPr": product.get("specialPrice"),
            "Vk0.SVonDat": product.get("specialStartDate"),
            "Vk0.SBisDat": product.get("specialEndDate"),
            "StSchl": product.get("taxKey"),
            "StSchlSz": product.get("taxRate"),
            "Bez3": product.get("source") or "",
            "customsTariffNumber": product.get("customsTariffNumber"),
            "weightGrossKg": product.get("weightGrossKg"),
            "weightNetKg": product.get("weightNetKg"),
            "warehouseNumber": product.get("warehouseNumber"),
            "stock": product.get("stock"),
            "storageLocation": product.get("storageLocation"),
        }
        for index, field_name in enumerate(self.PRODUCT_IMAGE_FIELDS):
            record[field_name] = images[index] if index < len(images) else ""
        self._records = [record]
        self._last_result = {"recordCount": 1, "returnedCount": 1}

    @staticmethod
    def _first_value(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return str(value or "").strip()

    @staticmethod
    def _normalize_images(images: Any) -> list[str]:
        if isinstance(images, str):
            return [images] if images.strip() else []
        if not isinstance(images, list):
            return []
        result = []
        for image in images:
            if isinstance(image, str) and image.strip():
                result.append(image.strip())
            elif isinstance(image, dict):
                candidate = image.get("filename") or image.get("fileName") or image.get("path") or image.get("url")
                if candidate:
                    result.append(str(candidate).strip())
        return [image for image in result if image]

    @staticmethod
    def _parse_weight(text: str, label: str) -> Decimal | None:
        match = re.search(rf"{label}:\s*([\d,.]+)\s*kg", text, re.IGNORECASE)
        if not match:
            return None
        value = match.group(1).replace(",", ".")
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _to_decimal(value) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _parse_tax_rate(value) -> Decimal | None:
        if value in (None, ""):
            return None
        text = str(value).strip().replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return Decimal(match.group(0)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None
