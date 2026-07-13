from __future__ import annotations

from django.db import models

from products.models import Product


REWRITEABLE_PRODUCT_FIELD_TYPES = (
    models.CharField,
    models.TextField,
)

# Nur Beschreibungstexte eignen sich fuer AI-Rewrites; Identifier wie SKU,
# ERP-Nummer, GTIN oder der Shopware Bild-Sync-Hash duerfen nicht ueberschrieben werden.
REWRITEABLE_PRODUCT_BASE_FIELDS = ("description", "description_short")


def _rewriteable_product_field_names() -> set[str]:
    from modeltranslation.translator import NotRegistered, translator

    names = set(REWRITEABLE_PRODUCT_BASE_FIELDS)
    try:
        options = translator.get_options_for_model(Product)
    except NotRegistered:
        return names
    for base_name, translation_fields in options.local_fields.items():
        if base_name not in REWRITEABLE_PRODUCT_BASE_FIELDS:
            continue
        names.update(field.name for field in translation_fields)
    return names


def get_rewriteable_product_fields() -> list[models.Field]:
    allowed_names = _rewriteable_product_field_names()
    fields: list[models.Field] = []
    for field in Product._meta.get_fields():
        if not isinstance(field, models.Field):
            continue
        if field.auto_created or not getattr(field, "editable", False):
            continue
        if not field.concrete:
            continue
        if not isinstance(field, REWRITEABLE_PRODUCT_FIELD_TYPES):
            continue
        if field.name not in allowed_names:
            continue
        fields.append(field)
    return fields


def get_rewriteable_product_field_choices() -> list[tuple[str, str]]:
    return [
        (field.name, str(field.verbose_name))
        for field in get_rewriteable_product_fields()
    ]


def get_rewriteable_product_field_names() -> set[str]:
    return {field.name for field in get_rewriteable_product_fields()}
