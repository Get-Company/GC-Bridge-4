from __future__ import annotations


def ensure_swiss_customs_field_defaults(sender, **kwargs) -> None:
    from microtech.models import MicrotechSwissCustomsFieldMapping

    MicrotechSwissCustomsFieldMapping.ensure_defaults()
