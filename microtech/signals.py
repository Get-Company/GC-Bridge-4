from __future__ import annotations


def ensure_swiss_customs_field_defaults(sender, **kwargs) -> None:
    from microtech.models import MicrotechSwissCustomsFieldMapping

    MicrotechSwissCustomsFieldMapping.ensure_defaults()


def sync_order_rule_django_field_catalog(sender, **kwargs) -> None:
    from microtech.rule_builder import sync_django_field_catalog

    sync_django_field_catalog()
