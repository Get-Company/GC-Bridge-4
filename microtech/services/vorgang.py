from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechVorgangService(MicrotechDatasetService):
    dataset_name = "Vorgang"
    index_field = "BelegNr"
    default_fields = ("BelegNr", "VorgangArt", "AdrNr", "AuftrNr", "Dat", "Bez", "Netto", "Brutto", "Waehrung", "Status")
