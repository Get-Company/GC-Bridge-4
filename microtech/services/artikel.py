from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .base import MicrotechDatasetService


class MicrotechArtikelService(MicrotechDatasetService):
    dataset_name = "Artikel"
    index_field = "Nr"

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
        image_fields = ["Bild", "Bild2", "Bild3", "Bild4", "Bild5"]
        return [
            img
            for img in (self.get_field_img_filename(field) for field in image_fields)
            if img
        ]

    def get_tax_key(self) -> str:
        return str(self.get_field("StSchl") or "").strip()

    def get_tax_rate(self) -> Decimal | None:
        direct_rate = self._parse_tax_rate(self.get_field("StSchlSz"))
        if direct_rate is not None:
            return direct_rate

        key = self.get_tax_key().upper().replace(" ", "")
        if "M7" in key:
            return Decimal("7.00")
        if "M19" in key:
            return Decimal("19.00")

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
