from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechVorgangService(MicrotechDatasetService):
    dataset_name = "Vorgang"
    index_field = "BelegNr"
