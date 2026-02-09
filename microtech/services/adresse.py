from __future__ import annotations

from loguru import logger

from .base import MicrotechDatasetService


class MicrotechAdresseService(MicrotechDatasetService):
    dataset_name = "Adressen"
    index_field = "Nr"

    def get_next_nr(self):
        self._require_dataset()
        try:
            return self.dataset.SetupNr("")
        except Exception as exc:
            logger.error("Fehler bei der Adressnummernvergabe: {}", exc)
            self.cancel()
            return None
