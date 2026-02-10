from __future__ import annotations

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
