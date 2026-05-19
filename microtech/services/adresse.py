from __future__ import annotations

from loguru import logger

from .base import MicrotechDatasetService


class MicrotechAdresseService(MicrotechDatasetService):
    dataset_name = "Adressen"
    index_field = "Nr"
    default_fields = ("AdrNr", "AdrId", "Na1", "EMail1", "ReAnsNr", "LiAnsNr")

    def get_next_nr(self):
        logger.error("Adressnummernvergabe ist in GC-Bridge nicht mehr per COM verfuegbar.")
        return None
