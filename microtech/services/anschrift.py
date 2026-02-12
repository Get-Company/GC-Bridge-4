from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechAnschriftService(MicrotechDatasetService):
    dataset_name = "Anschriften"
    index_field = "AdrNrAnsNr"
