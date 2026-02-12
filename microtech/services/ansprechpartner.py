from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechAnsprechpartnerService(MicrotechDatasetService):
    dataset_name = "Ansprechpartner"
    index_field = "Nr"
