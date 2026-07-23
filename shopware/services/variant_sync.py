from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from core.services import BaseService
from products.models import Price, Product, ProductVariantAttribute, ProductVariantFamily, PropertyGroup, PropertyValue
from products.services.variant_family import ProductVariantFamilyResolverService, VariantFamilyResolution
from shopware.models import ShopwareSettings
from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService


DEFAULT_TAX_ID = "d391e13bdd95404a885f4ad28ea218e0"
REDUCED_TAX_ID = "be66a53eae3a49829f4a8c5959535501"


@dataclass(frozen=True, slots=True)
class ShopwareVariantSyncResult:
    family_slug: str
    parent_id: str
    variant_count: int
    skipped_count: int
    detached_count: int
    errors: tuple[str, ...]
    dry_run: bool


class ShopwareVariantSyncService(BaseService):
    """Synchronize a Shopware parent and its children derived from attributes."""

    model = ProductVariantFamily

    def __init__(self, *, product_service: ProductService | None = None) -> None:
        self.product_service = product_service or ProductService()
        self.media_sync_service = ProductMediaSyncService()
        self.resolver = ProductVariantFamilyResolverService()

    def preview(self, family: ProductVariantFamily) -> VariantFamilyResolution:
        return self.resolver.resolve(family)

    def sync(self, family: ProductVariantFamily, *, dry_run: bool = False) -> ShopwareVariantSyncResult:
        resolution = self.preview(family)
        if not resolution.attributes:
            return self._clear_empty_family(family=family, dry_run=dry_run)

        if not resolution.is_valid:
            errors = resolution.errors or ("Keine vollständigen Varianten erkannt.",)
            return ShopwareVariantSyncResult(
                family_slug=family.slug,
                parent_id=family.shopware_id,
                variant_count=len(resolution.variants),
                skipped_count=len(resolution.skipped),
                detached_count=0,
                errors=errors,
                dry_run=dry_run,
            )

        if dry_run:
            return ShopwareVariantSyncResult(
                family_slug=family.slug,
                parent_id=family.shopware_id,
                variant_count=len(resolution.variants),
                skipped_count=len(resolution.skipped),
                detached_count=0,
                errors=(),
                dry_run=True,
            )

        if not family.target_category.sw6_id:
            raise ValueError(f"Zielkategorie '{family.target_category}' hat keine Shopware-ID.")

        group_ids, value_ids = self._ensure_attribute_entities(resolution)
        child_ids = self._resolve_child_ids(resolution)
        self._remove_stale_child_options(
            resolution=resolution,
            child_ids=child_ids,
            value_ids=value_ids,
        )
        default_product = self._default_product(family=family, resolution=resolution)
        parent_id = self._ensure_parent(
            family=family,
            default_product=default_product,
            main_variant_id="",
        )
        self._upsert_children(
            resolution=resolution,
            parent_id=parent_id,
            child_ids=child_ids,
            value_ids=value_ids,
        )
        configurator_setting_ids = self._upsert_configurator_settings(
            parent_id=parent_id,
            resolution=resolution,
            value_ids=value_ids,
        )
        self._remove_stale_configurator_settings(
            parent_id=parent_id,
            expected_setting_ids=configurator_setting_ids,
        )
        self._ensure_parent(
            family=family,
            default_product=default_product,
            main_variant_id=child_ids[default_product.pk],
            group_ids=group_ids,
            resolution=resolution,
        )
        detached_count = self._detach_stale_children(
            family=family,
            active_product_ids=set(child_ids),
        )
        family.synced_products.set(child_ids)

        return ShopwareVariantSyncResult(
            family_slug=family.slug,
            parent_id=parent_id,
            variant_count=len(resolution.variants),
            skipped_count=len(resolution.skipped),
            detached_count=detached_count,
            errors=(),
            dry_run=False,
        )

    def _ensure_attribute_entities(self, resolution: VariantFamilyResolution) -> tuple[dict[int, str], dict[int, str]]:
        group_ids: dict[int, str] = {}
        value_ids: dict[int, str] = {}
        display_types_by_group_id = {
            attribute.property_group_id: attribute.display_type for attribute in resolution.attributes
        }

        for attribute in resolution.attributes:
            group_ids[attribute.property_group_id] = self._ensure_property_group(
                attribute.property_group,
                display_type=attribute.display_type,
            )

        values = {
            value.pk: value
            for variant in resolution.variants
            for value in variant.option_values
        }
        for value in values.values():
            value_ids[value.pk] = self._ensure_property_value(
                value,
                group_id=group_ids[value.group_id],
                display_type=display_types_by_group_id[value.group_id],
            )

        return group_ids, value_ids

    def _ensure_property_group(self, group: PropertyGroup, *, display_type: str) -> str:
        group_id = group.shopware_id
        if not group_id:
            result = self.product_service.request_post(
                "/search/property-group",
                payload={
                    "filter": [{"type": "equals", "field": "name", "value": group.name}],
                    "limit": 2,
                },
            )
            rows = (result or {}).get("data", []) or []
            group_id = self.product_service._entity_id(rows[0]) if rows else ""
            group_id = group_id or self._stable_id("property-group", group.external_key or group.name)
            group.shopware_id = group_id
            group.save(update_fields=("shopware_id", "updated_at"))
        self.product_service.bulk_upsert(
            [
                {
                    "id": group_id,
                    "name": group.name,
                    "displayType": self._shopware_group_display_type(display_type),
                }
            ],
            entity_name="property_group",
        )
        return group_id

    def _ensure_property_value(self, value: PropertyValue, *, group_id: str, display_type: str) -> str:
        value_id = value.shopware_id
        if not value_id:
            result = self.product_service.request_post(
                "/search/property-group-option",
                payload={
                    "filter": [
                        {"type": "equals", "field": "groupId", "value": group_id},
                        {"type": "equals", "field": "name", "value": value.name},
                    ],
                    "limit": 2,
                },
            )
            rows = (result or {}).get("data", []) or []
            value_id = self.product_service._entity_id(rows[0]) if rows else ""
            value_id = value_id or self._stable_id(
                "property-value",
                value.group.external_key or value.group.name,
                value.external_key or value.name,
            )
            value.shopware_id = value_id
            value.save(update_fields=("shopware_id", "updated_at"))

        payload = {"id": value_id, "groupId": group_id, "name": value.name}
        if display_type == ProductVariantAttribute.DisplayType.IMAGE:
            if not value.image_id:
                raise ValueError(f"Attributwert '{value}' hat kein Auswahlbild.")
            media_id, media_entity, media_upload = self.media_sync_service.get_image_media_payload(image=value.image)
            self.media_sync_service.sync_media_assets(
                product_service=self.product_service,
                media_entities=[media_entity],
                media_uploads=[media_upload],
            )
            payload["mediaId"] = media_id
        self.product_service.bulk_upsert([payload], entity_name="property_group_option")
        return value_id

    def _resolve_child_ids(self, resolution: VariantFamilyResolution) -> dict[int, str]:
        product_numbers = [variant.product.erp_nr for variant in resolution.variants]
        number_to_id = self.product_service.get_sku_map(product_numbers)
        missing = [number for number in product_numbers if not number_to_id.get(number)]
        if missing:
            raise ValueError(
                "Shopware-Kindprodukte fehlen. Zuerst den normalen Produktsync ausführen: " + ", ".join(missing)
            )
        return {variant.product.pk: number_to_id[variant.product.erp_nr] for variant in resolution.variants}

    def _ensure_parent(
        self,
        *,
        family: ProductVariantFamily,
        default_product: Product,
        main_variant_id: str,
        group_ids: dict[int, str] | None = None,
        resolution: VariantFamilyResolution | None = None,
    ) -> str:
        parent_id = family.shopware_id or self.product_service.find_sku_by_number(family.shopware_product_number)
        parent_id = parent_id or self._stable_id("variant-parent", family.slug, family.shopware_product_number)
        payload = {
            "id": parent_id,
            "productNumber": family.shopware_product_number,
            "name": family.name,
            "description": family.description or default_product.description or "",
            "active": family.is_active,
            # Shopware requires stock for every newly created product, including
            # a non-sellable variant parent. Stock and availability are provided
            # by the actual child products, so the parent deliberately stays at 0.
            "stock": 0,
            "isCloseout": False,
            "taxId": self._tax_id(default_product),
            "categories": [{"id": family.target_category.sw6_id}],
        }
        parent_visibilities = self._parent_visibilities(parent_id=parent_id)
        if parent_visibilities:
            payload["visibilities"] = parent_visibilities
        parent_media, _media_entities, _media_uploads = self.media_sync_service.get_product_media_payload(
            product=default_product,
            product_id=parent_id,
        )
        if parent_media:
            # The media asset is already owned by the Django-maintained default
            # child product. The parent only gets its own Shopware relation and
            # cover, so --skip-product-sync does not upload or replace images.
            payload["media"] = parent_media
            payload["coverId"] = parent_media[0]["id"]
        parent_price = self._parent_price(default_product)
        if parent_price:
            payload["price"] = parent_price

        # Variant-listing settings are stored as one embedded Shopware field.
        # Sending the values as top-level product properties is silently ignored
        # by the sync API, leaving Shopware to choose an arbitrary child for
        # listings and the initial product-detail selection.
        variant_listing_config = {"displayParent": True}
        if main_variant_id:
            variant_listing_config["mainVariantId"] = main_variant_id
        if group_ids and resolution:
            variant_listing_config["configuratorGroupConfig"] = [
                {
                    "id": group_ids[attribute.property_group_id],
                    "expressionForListings": False,
                    "position": attribute.position,
                }
                for attribute in resolution.attributes
            ]
        payload["variantListingConfig"] = variant_listing_config
        self.product_service.bulk_upsert([payload])
        if family.shopware_id != parent_id:
            family.shopware_id = parent_id
            family.save(update_fields=("shopware_id", "updated_at"))
        return parent_id

    def _upsert_children(
        self,
        *,
        resolution: VariantFamilyResolution,
        parent_id: str,
        child_ids: dict[int, str],
        value_ids: dict[int, str],
    ) -> None:
        payload = [
            {
                "id": child_ids[variant.product.pk],
                "productNumber": variant.product.erp_nr,
                "parentId": parent_id,
                "options": [{"id": value_ids[value.pk]} for value in variant.option_values],
            }
            for variant in resolution.variants
        ]
        self.product_service.bulk_upsert(payload)

    def _remove_stale_child_options(
        self,
        *,
        resolution: VariantFamilyResolution,
        child_ids: dict[int, str],
        value_ids: dict[int, str],
    ) -> int:
        """Remove option mappings that no longer describe a child variant.

        Shopware's product upsert adds associations but does not reliably replace
        existing ``product_option`` mappings.  Reconcile those mappings first so
        a changed axis or option cannot leave an obsolete configuration behind.
        """
        expected_option_ids_by_child_id = {
            child_ids[variant.product.pk]: {value_ids[value.pk] for value in variant.option_values}
            for variant in resolution.variants
        }
        existing_option_ids_by_child_id = self.product_service.get_product_option_map(
            list(expected_option_ids_by_child_id)
        )
        if not isinstance(existing_option_ids_by_child_id, dict):
            return 0

        payload = [
            {"productId": child_id, "optionId": option_id}
            for child_id, expected_option_ids in expected_option_ids_by_child_id.items()
            for option_id in sorted(existing_option_ids_by_child_id.get(child_id, set()) - expected_option_ids)
        ]
        if payload:
            self.product_service.bulk_delete_product_options(payload)
        return len(payload)

    def _upsert_configurator_settings(
        self,
        *,
        parent_id: str,
        resolution: VariantFamilyResolution,
        value_ids: dict[int, str],
    ) -> set[str]:
        option_values_by_group: dict[int, set[int]] = {}
        for variant in resolution.variants:
            for value in variant.option_values:
                option_values_by_group.setdefault(value.group_id, set()).add(value.pk)

        payload: list[dict] = []
        setting_ids: set[str] = set()
        for attribute in resolution.attributes:
            for value_id in sorted(option_values_by_group.get(attribute.property_group_id, set())):
                shopware_option_id = value_ids[value_id]
                setting_id = self._stable_id("configurator-setting", parent_id, shopware_option_id)
                setting_ids.add(setting_id)
                payload.append(
                    {
                        "id": setting_id,
                        "productId": parent_id,
                        "optionId": shopware_option_id,
                        "position": attribute.position,
                    }
                )
        self.product_service.bulk_upsert(payload, entity_name="product_configurator_setting")
        return setting_ids

    def _remove_stale_configurator_settings(
        self,
        *,
        parent_id: str,
        expected_setting_ids: set[str],
    ) -> int:
        """Remove parent configurator settings no longer derived from the family.

        Property groups and option values are shared Shopware entities, so they
        must remain intact.  Only the parent-specific configurator relations
        are safe to remove here.
        """
        stale_setting_ids: set[str] = set()
        page = 1
        limit = 500
        while True:
            result = self.product_service.request_post(
                "/search/product-configurator-setting",
                payload={
                    "filter": [{"type": "equals", "field": "productId", "value": parent_id}],
                    "limit": limit,
                    "page": page,
                },
            )
            rows = (result or {}).get("data", []) or []
            stale_setting_ids.update(
                setting_id
                for row in rows
                if (setting_id := self.product_service._entity_id(row)) and setting_id not in expected_setting_ids
            )
            if len(rows) < limit:
                break
            page += 1

        for setting_id in sorted(stale_setting_ids):
            self.product_service.request_delete(f"/product-configurator-setting/{setting_id}")
        return len(stale_setting_ids)

    def _clear_empty_family(self, *, family: ProductVariantFamily, dry_run: bool) -> ShopwareVariantSyncResult:
        """Detach children and remove parent configurator settings after the final axis is deleted."""
        parent_id = family.shopware_id
        if dry_run:
            return ShopwareVariantSyncResult(
                family_slug=family.slug,
                parent_id=parent_id,
                variant_count=0,
                skipped_count=0,
                detached_count=0,
                errors=(),
                dry_run=dry_run,
            )

        parent_id = parent_id or self.product_service.find_sku_by_number(family.shopware_product_number)
        if not parent_id:
            return ShopwareVariantSyncResult(
                family_slug=family.slug,
                parent_id="",
                variant_count=0,
                skipped_count=0,
                detached_count=0,
                errors=(),
                dry_run=False,
            )

        detached_count = self._detach_stale_children(family=family, active_product_ids=set())
        self._remove_stale_configurator_settings(parent_id=parent_id, expected_setting_ids=set())
        self.product_service.bulk_upsert(
            [
                {
                    "id": parent_id,
                    "variantListingConfig": {
                        "displayParent": True,
                        "configuratorGroupConfig": [],
                    },
                }
            ]
        )
        family.synced_products.clear()
        return ShopwareVariantSyncResult(
            family_slug=family.slug,
            parent_id=parent_id,
            variant_count=0,
            skipped_count=0,
            detached_count=detached_count,
            errors=(),
            dry_run=False,
        )

    def _detach_stale_children(self, *, family: ProductVariantFamily, active_product_ids: set[int]) -> int:
        stale_products = list(family.synced_products.exclude(pk__in=active_product_ids).only("id", "erp_nr"))
        if not stale_products:
            return 0

        shopware_ids_by_number = self.product_service.get_sku_map(
            [product.erp_nr for product in stale_products]
        )
        stale_child_ids = {
            shopware_ids_by_number[product.erp_nr]
            for product in stale_products
            if shopware_ids_by_number.get(product.erp_nr)
        }
        self._remove_all_child_options(child_ids=stale_child_ids)
        payload = [
            {
                "id": shopware_ids_by_number[product.erp_nr],
                "productNumber": product.erp_nr,
                "parentId": None,
                "options": [],
            }
            for product in stale_products
            if shopware_ids_by_number.get(product.erp_nr)
        ]
        self.product_service.bulk_upsert(payload)
        return len(payload)

    def _remove_all_child_options(self, *, child_ids: set[str]) -> int:
        """Remove every variant option from children detached from this family."""
        existing_option_ids_by_child_id = self.product_service.get_product_option_map(sorted(child_ids))
        if not isinstance(existing_option_ids_by_child_id, dict):
            return 0

        payload = [
            {"productId": child_id, "optionId": option_id}
            for child_id in sorted(child_ids)
            for option_id in sorted(existing_option_ids_by_child_id.get(child_id, set()))
        ]
        if payload:
            self.product_service.bulk_delete_product_options(payload)
        return len(payload)

    @staticmethod
    def _stable_id(*parts: str) -> str:
        source = "|".join(str(part).strip() for part in parts)
        return hashlib.md5(f"gc-bridge-variant|{source}".encode("utf-8")).hexdigest()

    def _parent_visibilities(self, *, parent_id: str) -> list[dict[str, str | int]]:
        """Expose a variant parent in every actively configured sales channel.

        The actual child products may already be visible in Shopware, but a new
        parent has no visibility relation of its own. Without this relation the
        Storefront and UCP catalog cannot list the parent product.
        """
        sales_channel_ids = sorted(
            {
                str(sales_channel_id).strip()
                for sales_channel_id in ShopwareSettings.objects.filter(is_active=True).values_list(
                    "sales_channel_id", flat=True
                )
                if str(sales_channel_id).strip()
            }
        )
        return [
            {
                "id": self._stable_id("product-visibility", parent_id, sales_channel_id),
                "salesChannelId": sales_channel_id,
                "visibility": 30,
            }
            for sales_channel_id in sales_channel_ids
        ]

    @staticmethod
    def _shopware_group_display_type(display_type: str) -> str:
        return {"color": "color", "image": "media"}.get(display_type, "text")

    @staticmethod
    def _default_product(*, family: ProductVariantFamily, resolution: VariantFamilyResolution) -> Product:
        if family.default_product_id:
            for variant in resolution.variants:
                if variant.product.pk == family.default_product_id:
                    return variant.product
        return resolution.variants[0].product

    @staticmethod
    def _tax_id(product: Product) -> str:
        tax = product.tax
        if tax and tax.shopware_id:
            return str(tax.shopware_id).strip()
        if tax and tax.rate == Decimal("7.00"):
            return REDUCED_TAX_ID
        return DEFAULT_TAX_ID

    @staticmethod
    def _parent_price(product: Product) -> list[dict]:
        default_channel = ShopwareSettings.objects.filter(is_active=True, is_default=True).first()
        if not default_channel or not default_channel.currency_id:
            return []
        price = Price.objects.filter(product=product, sales_channel=default_channel).first()
        if not price:
            return []
        return [
            {
                "currencyId": default_channel.currency_id,
                "gross": price.get_current_brutto_price(as_float=True),
                "net": price.get_current_price(as_float=True),
                "linked": True,
            }
        ]
