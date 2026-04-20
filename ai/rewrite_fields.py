from __future__ import annotations

from django.db import models

from products.models import Product


REWRITEABLE_PRODUCT_FIELD_TYPES = (
    models.CharField,
    models.TextField,
)


def get_rewriteable_product_fields() -> list[models.Field]:
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
        fields.append(field)
    return fields


def get_rewriteable_product_field_choices() -> list[tuple[str, str]]:
    return [
        (field.name, str(field.verbose_name))
        for field in get_rewriteable_product_fields()
    ]


def get_rewriteable_product_field_names() -> set[str]:
    return {field.name for field in get_rewriteable_product_fields()}
