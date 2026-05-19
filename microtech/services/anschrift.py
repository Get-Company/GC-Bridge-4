from __future__ import annotations

from .base import MicrotechDatasetService


class MicrotechAnschriftService(MicrotechDatasetService):
    dataset_name = "Anschriften"
    index_field = "AdrNrAnsNr"
    default_fields = (
        "ID",
        "AdrNr",
        "AnsNr",
        "Na1",
        "Na2",
        "Na3",
        "Str",
        "PLZ",
        "Ort",
        "Land",
        "EMail1",
        "Tel",
        "Abt",
        "StdLiKz",
        "StdReKz",
    )
