from modeltranslation.translator import TranslationOptions, register

from .models import Category, Product, PropertyGroup, PropertyValue


@register(Product)
class ProductTranslationOptions(TranslationOptions):
    fields = (
        "name",
        "description",
        "description_short",
        "unit",
    )


@register(Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(PropertyGroup)
class PropertyGroupTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(PropertyValue)
class PropertyValueTranslationOptions(TranslationOptions):
    fields = ("name",)
