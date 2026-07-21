from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Prefetch
from django.db.models import Q

from core.services import BaseService
from products.models import Product, ProductProperty, ProductVariantAttribute, ProductVariantFamily, PropertyValue


@dataclass(frozen=True, slots=True)
class ResolvedVariant:
    """One existing Microtech-backed product and its derived variant options."""

    product: Product
    option_values: tuple[PropertyValue, ...]

    @property
    def option_key(self) -> tuple[int, ...]:
        return tuple(value.pk for value in self.option_values)


@dataclass(frozen=True, slots=True)
class SkippedVariantCandidate:
    product: Product
    reason: str


@dataclass(frozen=True, slots=True)
class VariantFamilyResolution:
    family: ProductVariantFamily
    attributes: tuple[ProductVariantAttribute, ...]
    variants: tuple[ResolvedVariant, ...]
    skipped: tuple[SkippedVariantCandidate, ...]
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors and bool(self.variants)


class ProductVariantFamilyResolverService(BaseService):
    """Derive Shopware variants from existing product properties.

    The service never creates a cartesian product.  It only turns existing
    Microtech-backed products into variants when their marked attribute values
    form one complete, unique combination.
    """

    model = ProductVariantFamily

    def resolve(self, family: ProductVariantFamily) -> VariantFamilyResolution:
        attributes = tuple(
            family.variant_attributes.select_related("property_group", "fallback_value", "fallback_value__image")
            .order_by("position", "property_group__name", "id")
        )
        if not attributes:
            return VariantFamilyResolution(
                family=family,
                attributes=(),
                variants=(),
                skipped=(),
                errors=("Die Variantenfamilie hat keine markierten Variantenattribute.",),
            )

        products = (
            family.candidate_products()
            .select_related("tax")
            .prefetch_related(
                Prefetch(
                    "product_properties",
                    queryset=ProductProperty.objects.select_related("value", "value__group", "value__image").order_by(
                        "value__group_id", "value_id"
                    ),
                    to_attr="prefetched_variant_properties",
                )
            )
            .order_by("erp_nr", "id")
        )

        variants: list[ResolvedVariant] = []
        skipped: list[SkippedVariantCandidate] = []
        errors: list[str] = []
        seen_combinations: dict[tuple[int, ...], Product] = {}

        for product in products:
            values_by_group: dict[int, list[PropertyValue]] = defaultdict(list)
            for product_property in product.prefetched_variant_properties:
                values_by_group[product_property.value.group_id].append(product_property.value)

            option_values: list[PropertyValue] = []
            incomplete_reasons: list[str] = []
            for attribute in attributes:
                values = values_by_group.get(attribute.property_group_id, [])
                if len(values) == 1:
                    option_values.append(values[0])
                    continue
                if not values and attribute.fallback_value_id:
                    option_values.append(attribute.fallback_value)
                    continue
                if len(values) > 1:
                    incomplete_reasons.append(
                        f"{attribute.property_group.name}: mehrere Werte ({', '.join(value.name for value in values)})"
                    )
                else:
                    incomplete_reasons.append(f"{attribute.property_group.name}: kein Wert")

            if incomplete_reasons:
                skipped.append(SkippedVariantCandidate(product=product, reason="; ".join(incomplete_reasons)))
                continue

            variant = ResolvedVariant(product=product, option_values=tuple(option_values))
            duplicate = seen_combinations.get(variant.option_key)
            if duplicate:
                option_label = " / ".join(value.name for value in variant.option_values)
                errors.append(
                    f"Doppelte Variantenkombination '{option_label}' bei {duplicate.erp_nr} und {product.erp_nr}."
                )
                continue
            seen_combinations[variant.option_key] = product
            variants.append(variant)

        if family.default_product_id and not any(variant.product.pk == family.default_product_id for variant in variants):
            errors.append("Die konfigurierte Standardvariante ergibt keine vollständige Variantenkombination.")

        image_groups = {
            attribute.property_group_id: attribute.property_group.name
            for attribute in attributes
            if attribute.display_type == ProductVariantAttribute.DisplayType.IMAGE
        }
        missing_images: dict[int, set[str]] = defaultdict(set)
        for variant in variants:
            for value in variant.option_values:
                if value.group_id in image_groups and not value.image_id:
                    missing_images[value.group_id].add(value.name)
        for group_id, names in sorted(missing_images.items(), key=lambda item: image_groups[item[0]]):
            errors.append(
                f"Bilddarstellung für '{image_groups[group_id]}' ohne Auswahlbild: {', '.join(sorted(names))}."
            )

        return VariantFamilyResolution(
            family=family,
            attributes=attributes,
            variants=tuple(variants),
            skipped=tuple(skipped),
            errors=tuple(errors),
        )

    def families_for_product(self, product: Product) -> tuple[ProductVariantFamily, ...]:
        return tuple(
            ProductVariantFamily.objects.filter(
                Q(source_categories__product=product) | Q(synced_products=product),
                is_active=True,
            )
            .distinct()
            .order_by("name", "id")
        )
