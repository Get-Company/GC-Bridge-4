from modeltranslation.translator import TranslationOptions, register

from .models import Category, Product


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
