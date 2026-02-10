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
