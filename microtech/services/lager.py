from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechLagerService(MicrotechDatasetService):
    dataset_name = "Lager"
    index_field = "ArtNrLagNr"

    def __init__(self, *, erp, lager_nr: int = 1, **kwargs) -> None:
        super().__init__(erp=erp, **kwargs)
        self.lager_nr = lager_nr

    def get_stock(self, art_nr: str, *, lager_nr: int | None = None):
        lager_nr = self.lager_nr if lager_nr is None else lager_nr
        if not art_nr:
            return None
        if not self.find([art_nr, lager_nr]):
            return None
        return self.get_field("Mge")

    def get_storage_location(self, art_nr: str, *, lager_nr: int | None = None):
        lager_nr = self.lager_nr if lager_nr is None else lager_nr
        if not art_nr:
            return None
        if not self.find([art_nr, lager_nr]):
            return None
        return self.get_field("Pos")
