from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechAnsprechpartnerService(MicrotechDatasetService):
    dataset_name = "Ansprechpartner"
    index_field = "AdrNrAnsNrAspNr"
    default_fields = (
        "ID",
        "AdrNr",
        "AnsNr",
        "AspNr",
        "Anr",
        "VNa",
        "NNa",
        "Ansp",
        "EMail1",
        "Tel1",
        "Abt",
        "StdKz",
    )
