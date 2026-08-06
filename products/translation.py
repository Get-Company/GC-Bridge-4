from modeltranslation.translator import TranslationOptions, register

from .models import ArchivedProduct, Category, Product, ProductVariantFamily, PropertyGroup, PropertyValue


@register(Product)
class ProductTranslationOptions(TranslationOptions):
    fields = (
        "name",
        "description",
        "description_short",
        "unit",
    )


@register(ArchivedProduct)
class ArchivedProductTranslationOptions(ProductTranslationOptions):
    """The archive proxy shares Product's translated fields."""


@register(Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = (
        "name",
        "description",
        "description_short",
        "meta_title",
        "meta_description",
        "meta_keywords",
    )


@register(PropertyGroup)
class PropertyGroupTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(PropertyValue)
class PropertyValueTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(ProductVariantFamily)
class ProductVariantFamilyTranslationOptions(TranslationOptions):
    """Customer-visible content of the Shopware variant parent."""

    fields = (
        "name",
        "description",
    )
