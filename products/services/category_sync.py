from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from django.db import transaction
from django.utils.text import slugify
from loguru import logger

from core.services import BaseService
from products.models import Category, Product, ProductVariantFamily
from shopware.services.shopware6 import Shopware6Service


DEFAULT_SHOPWARE6_CATEGORY_ROOTS = ("Deutsch", "Schweiz")


class ShopwareCategorySyncService(BaseService):
    """Importiert Shopware-6-Kategorien inklusive ihrer Übersetzungen in die Bridge."""

    model = Category
    search_path = "/search/category"

    def sync_from_shopware(
        self,
        *,
        limit: int | None = None,
        page_size: int = 100,
        shopware_service: Shopware6Service | None = None,
        root_names: tuple[str, ...] = DEFAULT_SHOPWARE6_CATEGORY_ROOTS,
        sync_product_assignments: bool = True,
    ) -> dict[str, int]:
        page_size = max(1, min(int(page_size or 100), 500))
        service = shopware_service or Shopware6Service()
        rows: list[dict[str, Any]] = []
        page = 1

        while True:
            remaining = None if limit is None else max(limit - len(rows), 0)
            if remaining == 0:
                break

            batch_limit = min(page_size, remaining) if remaining is not None else page_size
            response = service.request_post(
                self.search_path,
                payload=self._search_payload(page=page, limit=batch_limit),
            )
            batch = [row for row in ((response or {}).get("data") or []) if isinstance(row, dict)]
            if not batch:
                break
            rows.extend(batch)

            total = self._to_int((response or {}).get("total"))
            if len(batch) < batch_limit or (total and len(rows) >= total):
                break
            page += 1

        remote_categories, ignored_outside_roots, skipped = self._scoped_categories(
            rows=rows,
            root_names=root_names,
        )
        summary = self._upsert_categories(remote_categories)
        summary["seen"] = len(rows)
        summary["scoped"] = len(remote_categories)
        summary["ignored_outside_roots"] = ignored_outside_roots
        summary["skipped"] += skipped
        if sync_product_assignments:
            summary.update(
                self._sync_product_assignments(
                    service=service,
                    category_ids_by_sw6_id={
                        category.sw6_id: category.pk
                        for category in Category.objects.filter(sw6_id__in=remote_categories)
                        if category.sw6_id
                    },
                    page_size=page_size,
                )
            )
        else:
            summary.update(self._empty_product_assignment_summary())
        return summary

    @classmethod
    def _scoped_categories(
        cls,
        *,
        rows: list[dict[str, Any]],
        root_names: tuple[str, ...],
    ) -> tuple[dict[str, dict[str, Any]], int, int]:
        """Keep only the requested SW6 category trees."""
        categories: dict[str, dict[str, Any]] = {}
        skipped = 0
        for row in rows:
            category = cls._normalize_entity(row)
            sw6_id = cls._text(category.get("id"))
            name = cls._text(category.get("name"))
            if not sw6_id or not name:
                skipped += 1
                logger.warning("Skipping Shopware category without id or name: {}", row)
                continue
            categories[sw6_id] = category

        requested_names = [cls._normalized_name(name) for name in root_names if cls._normalized_name(name)]
        if not requested_names:
            raise ValueError("At least one Shopware6 category root is required.")
        root_ids: list[str] = []
        missing_roots: list[str] = []
        for root_name in requested_names:
            matches = [
                category_id
                for category_id, category in categories.items()
                if cls._normalized_name(category.get("name")) == root_name
            ]
            if len(matches) == 1:
                root_ids.append(matches[0])
            elif not matches:
                missing_roots.append(root_name)
            else:
                raise ValueError(f"Shopware6 category root '{root_name}' is ambiguous: {', '.join(matches)}.")
        if missing_roots:
            raise ValueError("Shopware6 category roots not found: " + ", ".join(missing_roots))

        children_by_parent: dict[str, list[str]] = defaultdict(list)
        for category_id, category in categories.items():
            parent_id = cls._text(category.get("parentId"))
            if parent_id:
                children_by_parent[parent_id].append(category_id)
        selected_ids: set[str] = set()
        pending = deque(root_ids)
        while pending:
            category_id = pending.popleft()
            if category_id in selected_ids or category_id not in categories:
                continue
            selected_ids.add(category_id)
            pending.extend(children_by_parent.get(category_id, []))
        return (
            {category_id: categories[category_id] for category_id in selected_ids},
            len(categories) - len(selected_ids),
            skipped,
        )

    @classmethod
    def _sort_orders(cls, categories: dict[str, dict[str, Any]]) -> dict[str, int]:
        """Translate SW6's sibling ``afterCategoryId`` chains to local positions."""
        siblings_by_parent: dict[str, list[str]] = defaultdict(list)
        for category_id, category in categories.items():
            parent_id = cls._text(category.get("parentId"))
            siblings_by_parent[parent_id if parent_id in categories else ""].append(category_id)

        sort_orders: dict[str, int] = {}
        for sibling_ids in siblings_by_parent.values():
            sibling_set = set(sibling_ids)
            followers_by_after: dict[str, list[str]] = defaultdict(list)
            first_ids: list[str] = []
            for category_id in sibling_ids:
                after_id = cls._text(categories[category_id].get("afterCategoryId"))
                if after_id in sibling_set and after_id != category_id:
                    followers_by_after[after_id].append(category_id)
                else:
                    first_ids.append(category_id)

            def category_key(category_id: str) -> tuple[str, str]:
                return cls._normalized_name(categories[category_id].get("name")), category_id

            ordered_ids: list[str] = []
            visited: set[str] = set()

            def append_chain(category_id: str) -> None:
                if category_id in visited:
                    return
                visited.add(category_id)
                ordered_ids.append(category_id)
                for follower_id in sorted(followers_by_after.get(category_id, []), key=category_key):
                    append_chain(follower_id)

            for category_id in sorted(first_ids, key=category_key):
                append_chain(category_id)
            for category_id in sorted(sibling_ids, key=category_key):
                append_chain(category_id)
            for position, category_id in enumerate(ordered_ids, start=1):
                sort_orders[category_id] = position * 10
        return sort_orders

    def _sync_product_assignments(
        self,
        *,
        service: Shopware6Service,
        category_ids_by_sw6_id: dict[str, int],
        page_size: int,
    ) -> dict[str, int]:
        if not category_ids_by_sw6_id:
            return self._empty_product_assignment_summary()

        source_assignments = self._product_category_assignments(
            service=service,
            category_sw6_ids=set(category_ids_by_sw6_id),
            page_size=page_size,
        )
        source_product_ids = set(source_assignments)
        source_product_numbers = {
            assignment["product_number"]
            for assignment in source_assignments.values()
            if assignment["product_number"]
        }
        products_by_sku = {
            product.sku: product.pk
            for product in Product.objects.filter(sku__in=source_product_ids)
            if product.sku
        }
        products_by_erp_nr = {
            product.erp_nr: product.pk
            for product in Product.objects.filter(erp_nr__in=source_product_numbers)
        }
        product_ids_by_family_shopware_id: dict[str, set[int]] = defaultdict(set)
        for family in ProductVariantFamily.objects.filter(shopware_id__in=source_product_ids).prefetch_related(
            "synced_products"
        ):
            product_ids_by_family_shopware_id[family.shopware_id].update(
                family.synced_products.values_list("pk", flat=True)
            )
        resolved_product_ids: dict[str, set[int]] = {}
        for source_product_id, assignment in source_assignments.items():
            product_ids = set(product_ids_by_family_shopware_id[source_product_id])
            if source_product_id in products_by_sku:
                product_ids.add(products_by_sku[source_product_id])
            elif assignment["product_number"] in products_by_erp_nr:
                product_ids.add(products_by_erp_nr[assignment["product_number"]])
            resolved_product_ids[source_product_id] = product_ids
        desired_links = {
            (product_id, category_ids_by_sw6_id[category_sw6_id])
            for source_product_id, assignment in source_assignments.items()
            for category_sw6_id in assignment["category_sw6_ids"]
            for product_id in resolved_product_ids[source_product_id]
        }
        category_ids = set(category_ids_by_sw6_id.values())
        through_model = Product.categories.through
        existing_links = set(
            through_model.objects.filter(category_id__in=category_ids).values_list("product_id", "category_id")
        )
        new_links = desired_links - existing_links
        stale_links = existing_links - desired_links
        with transaction.atomic():
            if new_links:
                through_model.objects.bulk_create(
                    [
                        through_model(product_id=product_id, category_id=category_id)
                        for product_id, category_id in new_links
                    ],
                    ignore_conflicts=True,
                )
            if stale_links:
                for product_id, category_id in stale_links:
                    through_model.objects.filter(product_id=product_id, category_id=category_id).delete()
        return {
            "source_products": len(source_assignments),
            "matched_products": len(
                {product_id for product_ids in resolved_product_ids.values() for product_id in product_ids}
            ),
            "missing_products": sum(not product_ids for product_ids in resolved_product_ids.values()),
            "created_assignments": len(new_links),
            "existing_assignments": len(existing_links & desired_links),
            "removed_assignments": len(stale_links),
        }

    def _product_category_assignments(
        self,
        *,
        service: Shopware6Service,
        category_sw6_ids: set[str],
        page_size: int,
    ) -> dict[str, dict[str, Any]]:
        assignments: dict[str, dict[str, Any]] = {}
        page = 1
        while True:
            response = service.request_post(
                "/search/product",
                payload={
                    "page": page,
                    "limit": page_size,
                    "total-count-mode": 1,
                    # An empty association is removed by Shopware6Service's
                    # payload normalizer. Keep a concrete limit so SW6
                    # actually returns every product's category assignments.
                    "associations": {"categories": {"limit": 500}},
                },
            )
            rows = [row for row in ((response or {}).get("data") or []) if isinstance(row, dict)]
            if not rows:
                break
            for row in rows:
                product = self._normalize_entity(row)
                product_id = self._text(product.get("id"))
                product_number = self._text(product.get("productNumber"))
                if not product_id:
                    continue
                # ``categoryIds`` is the API-aware, inherited SW6 field. It
                # contains the category IDs of a parent on its variants as
                # well. The older ``categories`` association only exposed
                # direct rows here, which is why most category products were
                # missed in this shop.
                category_ids = {
                    category_id
                    for category_id in (self._text(value) for value in product.get("categoryIds") or [])
                    if category_id in category_sw6_ids
                }
                if not category_ids:
                    for category in product.get("categories") or []:
                        category_data = self._normalize_entity(category) if isinstance(category, dict) else {}
                        category_id = self._text(category_data.get("id"))
                        if category_id in category_sw6_ids:
                            category_ids.add(category_id)
                if category_ids:
                    assignments[product_id] = {
                        "product_number": product_number,
                        "category_sw6_ids": category_ids,
                    }
            total = self._to_int((response or {}).get("total"))
            if len(rows) < page_size or (total and page * page_size >= total):
                break
            page += 1
        return assignments

    @staticmethod
    def _empty_product_assignment_summary() -> dict[str, int]:
        return {
            "source_products": 0,
            "matched_products": 0,
            "missing_products": 0,
            "created_assignments": 0,
            "existing_assignments": 0,
            "removed_assignments": 0,
        }

    @classmethod
    def _search_payload(cls, *, page: int, limit: int) -> dict[str, Any]:
        return {
            "page": page,
            "limit": limit,
            "total-count-mode": 1,
            "associations": {
                "translations": {
                    "associations": {
                        "language": {
                            "associations": {
                                "locale": {},
                            },
                        },
                    },
                },
            },
        }

    def _upsert_categories(self, remote_categories: dict[str, dict[str, Any]]) -> dict[str, int]:
        summary = {
            "seen": len(remote_categories),
            "created": 0,
            "updated": 0,
            "skipped": 0,
        }
        if not remote_categories:
            return summary

        remote_ids = set(remote_categories)
        categories_by_sw6_id = {
            category.sw6_id: category
            for category in Category.objects.filter(sw6_id__in=remote_ids)
            if category.sw6_id
        }
        sort_orders = self._sort_orders(remote_categories)
        with transaction.atomic(), Category.objects.disable_mptt_updates():
            for sw6_id, remote_category in remote_categories.items():
                category = categories_by_sw6_id.get(sw6_id)

                defaults = self._category_defaults(remote_category)
                translations = self._translation_defaults(remote_category)
                if category is None:
                    category = Category(
                        sw6_id=sw6_id,
                        slug=self._build_unique_slug(defaults["name"], sw6_id),
                        **defaults,
                    )
                    summary["created"] += 1
                else:
                    for field_name, value in defaults.items():
                        setattr(category, field_name, value)
                    category.sw6_id = sw6_id
                    summary["updated"] += 1

                category.sort_order = sort_orders[sw6_id]
                for field_name, value in translations.items():
                    setattr(category, field_name, value)
                category.save()
                categories_by_sw6_id[sw6_id] = category

            for sw6_id, remote_category in remote_categories.items():
                parent_sw6_id = self._text(remote_category.get("parentId"))
                category = categories_by_sw6_id[sw6_id]
                if not parent_sw6_id or parent_sw6_id not in remote_categories:
                    Category.objects.filter(pk=category.pk).update(parent_id=None)
                    continue

                parent = categories_by_sw6_id.get(parent_sw6_id)
                if parent is None:
                    logger.warning(
                        "Shopware category {} references unavailable parent {}.",
                        sw6_id,
                        parent_sw6_id,
                    )
                    continue
                if parent.pk != category.pk:
                    Category.objects.filter(pk=category.pk).update(parent_id=parent.pk)

            Category.objects.rebuild()

        return summary

    @classmethod
    def _category_defaults(cls, category: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": cls._truncate(category.get("name"), 128),
            "description": cls._text(category.get("description")),
            "meta_title": cls._truncate(category.get("metaTitle"), 255),
            "meta_description": cls._text(category.get("metaDescription")),
            "meta_keywords": cls._truncate(category.get("keywords"), 255),
            "is_active": cls._to_bool(category.get("active"), default=True),
            "is_visible": cls._to_bool(category.get("visible"), default=True),
        }

    @classmethod
    def _translation_defaults(cls, category: dict[str, Any]) -> dict[str, str]:
        defaults: dict[str, str] = {}
        translations = category.get("translations") or []
        if not isinstance(translations, list):
            return defaults

        fields = {
            "name": ("name", 128),
            "description": ("description", None),
            "meta_title": ("metaTitle", 255),
            "meta_description": ("metaDescription", None),
            "meta_keywords": ("keywords", 255),
        }
        for translation in translations:
            data = cls._normalize_entity(translation)
            language_suffix = cls._language_suffix(data)
            if not language_suffix:
                continue
            for model_field, (shopware_field, max_length) in fields.items():
                if shopware_field not in data:
                    continue
                value = cls._text(data.get(shopware_field))
                defaults[f"{model_field}_{language_suffix}"] = (
                    cls._truncate(value, max_length) if max_length else value
                )
        return defaults

    @classmethod
    def _language_suffix(cls, translation: dict[str, Any]) -> str:
        language = translation.get("language") if isinstance(translation.get("language"), dict) else {}
        locale = language.get("locale") if isinstance(language.get("locale"), dict) else {}
        locale_code = cls._text(
            translation.get("localeCode")
            or translation.get("locale")
            or language.get("localeCode")
            or locale.get("code")
        ).lower().replace("_", "-")
        return {
            "de": "de",
            "de-de": "de",
            "en": "en",
            "en-gb": "en",
            "en-us": "en",
            "ch-de": "ch_de",
            "de-ch": "ch_de",
            "it-de": "it_de",
            "de-it": "it_de",
            "it-it": "it_it",
        }.get(locale_code, "")

    @classmethod
    def _build_unique_slug(cls, name: str, sw6_id: str) -> str:
        base_slug = slugify(name) or "kategorie"
        suffix = sw6_id[:8]
        candidate = base_slug[: 160 - len(suffix) - 1] + f"-{suffix}"
        index = 2
        while Category.objects.filter(slug=candidate).exists():
            indexed_suffix = f"-{suffix}-{index}"
            candidate = base_slug[: 160 - len(indexed_suffix)] + indexed_suffix
            index += 1
        return candidate

    @classmethod
    def _normalize_entity(cls, payload: dict[str, Any]) -> dict[str, Any]:
        attributes = payload.get("attributes")
        normalized = dict(attributes) if isinstance(attributes, dict) else dict(payload)
        normalized.setdefault("id", payload.get("id"))
        for source in (payload, attributes if isinstance(attributes, dict) else {}):
            for field_name, value in source.items():
                if field_name == "attributes":
                    continue
                if isinstance(value, dict):
                    normalized[field_name] = cls._normalize_entity(value)
                elif isinstance(value, list):
                    normalized[field_name] = [
                        cls._normalize_entity(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                elif field_name not in normalized:
                    normalized[field_name] = value
        return normalized

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @classmethod
    def _normalized_name(cls, value: Any) -> str:
        return " ".join(cls._text(value).casefold().split())

    @classmethod
    def _truncate(cls, value: Any, max_length: int | None) -> str:
        text = cls._text(value)
        return text[:max_length] if max_length else text

    @staticmethod
    def _to_bool(value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
