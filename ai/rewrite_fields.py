from __future__ import annotations

from django.db import models

from products.models import Category, Product


REWRITEABLE_FIELD_TYPES = (
    models.CharField,
    models.TextField,
)

# Beschreibungs- und SEO-Texte eignen sich fuer AI-Rewrites; Identifier wie SKU,
# ERP-Nummer, GTIN oder der Shopware Bild-Sync-Hash duerfen nicht ueberschrieben werden.
REWRITEABLE_PRODUCT_BASE_FIELDS = ("description", "description_short")
REWRITEABLE_CATEGORY_BASE_FIELDS = (
    "description",
    "description_short",
    "meta_title",
    "meta_description",
    "meta_keywords",
)


def _rewriteable_field_names(model, base_field_names: tuple[str, ...]) -> set[str]:
    from modeltranslation.translator import NotRegistered, translator

    names = set(base_field_names)
    try:
        options = translator.get_options_for_model(model)
    except NotRegistered:
        return names
    for base_name, translation_fields in options.local_fields.items():
        if base_name not in base_field_names:
            continue
        names.update(field.name for field in translation_fields)
    return names


def _get_rewriteable_fields(model, base_field_names: tuple[str, ...]) -> list[models.Field]:
    allowed_names = _rewriteable_field_names(model, base_field_names)
    fields: list[models.Field] = []
    for field in model._meta.get_fields():
        if not isinstance(field, models.Field):
            continue
        if field.auto_created or not getattr(field, "editable", False):
            continue
        if not field.concrete:
            continue
        if not isinstance(field, REWRITEABLE_FIELD_TYPES):
            continue
        if field.name not in allowed_names:
            continue
        fields.append(field)
    return fields


def get_rewriteable_product_fields() -> list[models.Field]:
    return _get_rewriteable_fields(Product, REWRITEABLE_PRODUCT_BASE_FIELDS)


def get_rewriteable_product_field_choices() -> list[tuple[str, str]]:
    return [
        (field.name, str(field.verbose_name))
        for field in get_rewriteable_product_fields()
    ]


def get_rewriteable_product_field_names() -> set[str]:
    return {field.name for field in get_rewriteable_product_fields()}


def get_rewriteable_category_fields() -> list[models.Field]:
    return _get_rewriteable_fields(Category, REWRITEABLE_CATEGORY_BASE_FIELDS)


def get_rewriteable_category_field_choices() -> list[tuple[str, str]]:
    return [
        (field.name, str(field.verbose_name))
        for field in get_rewriteable_category_fields()
    ]


def get_rewriteable_category_field_names() -> set[str]:
    return {field.name for field in get_rewriteable_category_fields()}
