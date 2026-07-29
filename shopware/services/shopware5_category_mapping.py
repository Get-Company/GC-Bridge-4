from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote

from django.db import transaction
from core.services import BaseService
from products.models import Category, Product
from shopware.services.shopware5 import Shopware5APIError, Shopware5ProductSyncService


DEFAULT_SHOPWARE5_CATEGORY_ROOTS = ("Deutsch", "Schweiz")


@dataclass(frozen=True, slots=True)
class Shopware5CategoryMappingSnapshot:
    """Read-only representation of one Shopware-5 category mapping run."""

    categories: dict[str, dict[str, Any]]
    root_ids: tuple[str, ...]
    product_numbers_by_category: dict[str, set[str]]
    article_count: int
    article_detail_count: int

    @property
    def assignment_count(self) -> int:
        return sum(len(product_numbers) for product_numbers in self.product_numbers_by_category.values())


class Shopware5CategoryMappingService(BaseService):
    """Import Shopware-5 category trees and ERP-number product assignments."""

    model = Category
    max_page_size = 1000
    max_article_detail_workers = 12

    def __init__(self, *, api_service: Shopware5ProductSyncService | None = None) -> None:
        self.api_service = api_service or Shopware5ProductSyncService()

    def collect_snapshot(
        self,
        *,
        root_names: Iterable[str] = DEFAULT_SHOPWARE5_CATEGORY_ROOTS,
        page_size: int = max_page_size,
        article_detail_workers: int = 6,
    ) -> Shopware5CategoryMappingSnapshot:
        """Read the requested Shopware trees and all article/category assignments.

        Shopware 5 exposes category assignments on an individual article, not on
        the category resource.  A failed article lookup aborts the complete run
        so a later reconciliation can never remove assignments from incomplete
        source data.
        """
        page_size = self._normalize_page_size(page_size)
        categories = self._get_categories(page_size=page_size)
        root_ids = self._find_root_ids(categories=categories, root_names=root_names)
        scoped_categories = self._scoped_categories(categories=categories, root_ids=root_ids)

        product_numbers_by_category = {category_id: set() for category_id in scoped_categories}
        article_rows = self._get_article_rows(page_size=page_size)
        article_ids = [self._text(article_row.get("id")) for article_row in article_rows]
        article_ids = [article_id for article_id in article_ids if article_id]
        article_detail_count = 0
        for article in self._get_articles(
            article_ids=article_ids,
            workers=self._normalize_article_detail_workers(article_detail_workers),
        ):
            article_detail_count += 1
            product_numbers = self._article_product_numbers(article)
            if not product_numbers:
                continue
            for category in self._as_dict_list(article.get("categories")):
                category_id = self._text(category.get("id"))
                if category_id in product_numbers_by_category:
                    product_numbers_by_category[category_id].update(product_numbers)

        return Shopware5CategoryMappingSnapshot(
            categories=scoped_categories,
            root_ids=tuple(root_ids),
            product_numbers_by_category=product_numbers_by_category,
            article_count=len(article_rows),
            article_detail_count=article_detail_count,
        )

    def preview(self, snapshot: Shopware5CategoryMappingSnapshot) -> dict[str, Any]:
        """Return a category-by-category source report without touching Django data."""
        snapshot = self._root_scoped_snapshot(snapshot)
        return {
            "roots": [snapshot.categories[root_id]["name"] for root_id in snapshot.root_ids],
            "categories": len(snapshot.categories),
            "articles": snapshot.article_count,
            "article_details": snapshot.article_detail_count,
            "assignments": snapshot.assignment_count,
            "category_reports": self._category_reports(snapshot),
        }

    def preview_category_comparison(
        self,
        snapshot: Shopware5CategoryMappingSnapshot,
        *,
        root_name: str,
        category_name: str,
    ) -> dict[str, Any]:
        """Compare one source category with its local category without writing data."""
        snapshot = self._root_scoped_snapshot(snapshot)
        root_id = self._snapshot_root_id(snapshot=snapshot, root_name=root_name)
        category_id = self._snapshot_category_id(
            snapshot=snapshot,
            root_id=root_id,
            category_name=category_name,
        )
        categories_by_sw5_id = self._existing_categories(snapshot)
        local_category = categories_by_sw5_id.get(category_id)
        source_product_numbers = sorted(snapshot.product_numbers_by_category[category_id])
        project_products = {
            product.erp_nr: product
            for product in Product.objects.filter(erp_nr__in=source_product_numbers).only(
                "id",
                "erp_nr",
                "name",
                "is_active",
            )
        }
        local_category_products = []
        if local_category is not None:
            local_category_products = list(
                Product.objects.filter(categories=local_category)
                .only("id", "erp_nr", "name", "is_active")
                .order_by("erp_nr", "id")
            )
        local_product_numbers = {product.erp_nr for product in local_category_products}

        return {
            "source_category": {
                "sw5_id": category_id,
                "name": snapshot.categories[category_id]["name"],
                "path": self._category_path(snapshot=snapshot, category_id=category_id),
                "root": snapshot.categories[root_id]["name"],
                "position": snapshot.categories[category_id]["position"],
            },
            "local_category": (
                {
                    "id": local_category.pk,
                    "name": local_category.name,
                    "path": local_category.get_category_path(),
                    "sw5_id": local_category.sw5_id or "",
                    "sw6_id": local_category.sw6_id or "",
                }
                if local_category is not None
                else None
            ),
            "source_product_numbers": source_product_numbers,
            "project_products": {
                product_number: {
                    "name": product.name or "",
                    "is_active": product.is_active,
                    "is_assigned": product_number in local_product_numbers,
                }
                for product_number, product in project_products.items()
            },
            "local_only_product_numbers": sorted(local_product_numbers - set(source_product_numbers)),
            "missing_in_project": sorted(set(source_product_numbers) - set(project_products)),
            "missing_assignment": sorted((set(project_products) - local_product_numbers)),
        }

    def preview_reconciliation_report(self, snapshot: Shopware5CategoryMappingSnapshot) -> dict[str, Any]:
        """Compare the selected SW5 trees with local categories without writing data."""
        snapshot = self._root_scoped_snapshot(snapshot)
        categories_by_sw5_id = self._existing_categories(snapshot)
        local_categories = list(
            Category.objects.only("id", "name", "parent_id", "sw5_id", "sw6_id", "sort_order", "is_active")
        )
        local_categories_by_pk = {category.pk: category for category in local_categories}
        local_category_ids = {category.pk for category in categories_by_sw5_id.values()}

        source_product_numbers = {
            product_number
            for product_numbers in snapshot.product_numbers_by_category.values()
            for product_number in product_numbers
        }
        products_by_erp_nr = Product.objects.in_bulk(source_product_numbers, field_name="erp_nr")
        local_product_numbers_by_category: dict[int, set[str]] = defaultdict(set)
        if local_category_ids:
            product_numbers_by_pk = dict(
                Product.objects.filter(categories__in=local_category_ids)
                .values_list("pk", "erp_nr")
                .distinct()
            )
            for product_id, category_id in Product.categories.through.objects.filter(
                category_id__in=local_category_ids
            ).values_list("product_id", "category_id"):
                product_number = product_numbers_by_pk.get(product_id)
                if product_number:
                    local_product_numbers_by_category[category_id].add(product_number)

        reports: list[dict[str, Any]] = []
        for sw5_id in self._category_ids_in_parent_order(snapshot.categories):
            source_category = snapshot.categories[sw5_id]
            local_category = categories_by_sw5_id.get(sw5_id)
            source_numbers = set(snapshot.product_numbers_by_category.get(sw5_id, set()))
            project_numbers = source_numbers & set(products_by_erp_nr)
            local_numbers = (
                local_product_numbers_by_category.get(local_category.pk, set()) if local_category is not None else set()
            )
            source_parent_id = source_category["parent_id"]
            expected_parent_sw5_id = source_parent_id if source_parent_id in snapshot.categories else ""
            local_parent = local_categories_by_pk.get(local_category.parent_id) if local_category is not None else None
            actual_parent_sw5_id = self._text(local_parent.sw5_id) if local_parent is not None else ""
            reports.append(
                {
                    "id": sw5_id,
                    "path": self._category_path(snapshot=snapshot, category_id=sw5_id),
                    "position": source_category["position"],
                    "active": source_category["active"],
                    "local_category": (
                        {
                            "id": local_category.pk,
                            "path": self._local_category_name_path(
                                category=local_category,
                                categories_by_pk=local_categories_by_pk,
                            ),
                            "sw5_id": self._text(local_category.sw5_id),
                            "sw6_id": self._text(local_category.sw6_id),
                            "position": local_category.sort_order,
                            "active": local_category.is_active,
                        }
                        if local_category is not None
                        else None
                    ),
                    "expected_parent_sw5_id": expected_parent_sw5_id,
                    "actual_parent_sw5_id": actual_parent_sw5_id,
                    "parent_matches": local_category is not None and expected_parent_sw5_id == actual_parent_sw5_id,
                    "position_matches": local_category is not None and source_category["position"] == local_category.sort_order,
                    "active_matches": local_category is not None and source_category["active"] == local_category.is_active,
                    "source_products": len(source_numbers),
                    "project_products": len(project_numbers),
                    "assigned_products": len(source_numbers & local_numbers),
                    "missing_in_project": sorted(source_numbers - set(products_by_erp_nr)),
                    "missing_assignment": sorted(project_numbers - local_numbers),
                    "local_only_product_numbers": sorted(local_numbers - source_numbers),
                }
            )

        return {
            "categories": len(reports),
            "recognized_categories": sum(report["local_category"] is not None for report in reports),
            "parent_matches": sum(report["parent_matches"] for report in reports),
            "position_matches": sum(report["position_matches"] for report in reports),
            "active_matches": sum(report["active_matches"] for report in reports),
            "reports": reports,
        }

    def apply(
        self,
        snapshot: Shopware5CategoryMappingSnapshot,
        *,
        replace_assignments: bool = False,
    ) -> dict[str, Any]:
        """Persist the source hierarchy and its product assignments locally."""
        snapshot = self._root_scoped_snapshot(snapshot)
        categories_by_sw5_id = self._existing_categories(snapshot)
        unmapped_category_ids = [
            category_id
            for category_id in self._category_ids_in_parent_order(snapshot.categories)
            if category_id not in categories_by_sw5_id
        ]
        if unmapped_category_ids:
            paths = ", ".join(
                self._category_path(snapshot=snapshot, category_id=category_id)
                for category_id in unmapped_category_ids
            )
            raise Shopware5APIError(
                "Keine eindeutige lokale Kategorie fuer den vollstaendigen Shopware-5-Pfad gefunden: "
                f"{paths}. Es wurden keine lokalen Kategorien oder Produktzuordnungen veraendert."
            )

        with transaction.atomic(), Category.objects.disable_mptt_updates():
            updated = 0
            for sw5_id in self._category_ids_in_parent_order(snapshot.categories):
                remote_category = snapshot.categories[sw5_id]
                category = categories_by_sw5_id[sw5_id]
                updated += 1

                category.name = remote_category["name"]
                category.sw5_id = sw5_id
                category.sort_order = remote_category["position"]
                category.is_active = remote_category["active"]
                category.save()
                categories_by_sw5_id[sw5_id] = category

            for sw5_id, remote_category in snapshot.categories.items():
                category = categories_by_sw5_id[sw5_id]
                parent = categories_by_sw5_id.get(remote_category["parent_id"])
                parent_id = parent.pk if parent and parent.pk != category.pk else None
                Category.objects.filter(pk=category.pk).update(parent_id=parent_id)

            Category.objects.rebuild()

        assignment_result = self._apply_assignments(
            snapshot=snapshot,
            categories_by_sw5_id=categories_by_sw5_id,
            replace_assignments=replace_assignments,
        )
        return {
            "created_categories": 0,
            "updated_categories": updated,
            "categories": len(snapshot.categories),
            "articles": snapshot.article_count,
            "article_details": snapshot.article_detail_count,
            "source_assignments": snapshot.assignment_count,
            "replace_assignments": replace_assignments,
            **assignment_result,
        }

    def _get_categories(self, *, page_size: int) -> dict[str, dict[str, Any]]:
        rows = self._get_paged_rows(path="/categories", page_size=page_size)
        categories: dict[str, dict[str, Any]] = {}
        for row in rows:
            category_id = self._text(row.get("id"))
            name = self._text(row.get("name"))
            if not category_id or not name:
                continue
            categories[category_id] = {
                "id": category_id,
                "parent_id": self._text(row.get("parentId")),
                "name": name[:128],
                "position": self._to_nonnegative_int(row.get("position"), default=1000),
                "active": self._to_bool(row.get("active"), default=True),
            }
        if not categories:
            raise Shopware5APIError("Shopware5 returned no usable categories.")
        return categories

    def _get_article_rows(self, *, page_size: int) -> list[dict[str, Any]]:
        return self._get_paged_rows(path="/articles", page_size=page_size)

    def _get_paged_rows(self, *, path: str, page_size: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            response = self.api_service.get(f"{path}?limit={page_size}&start={start}")
            batch = self._as_dict_list(response.get("data"))
            rows.extend(batch)
            total = self._to_nonnegative_int(response.get("total"), default=0)
            if not batch or len(batch) < page_size or (total and len(rows) >= total):
                break
            start += len(batch)
        return rows

    def _get_article(self, article_id: str) -> dict[str, Any]:
        response = self.api_service.get(f"/articles/{quote(article_id, safe='')}")
        article = response.get("data")
        if not isinstance(article, dict):
            raise Shopware5APIError(f"Shopware5 article {article_id} returned no article data.")
        return article

    def _get_articles(self, *, article_ids: list[str], workers: int) -> list[dict[str, Any]]:
        if workers == 1 or len(article_ids) <= 1:
            return [self._get_article(article_id) for article_id in article_ids]
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shopware5-article") as executor:
            return list(executor.map(self._get_article, article_ids))

    @classmethod
    def _find_root_ids(
        cls,
        *,
        categories: dict[str, dict[str, Any]],
        root_names: Iterable[str],
    ) -> list[str]:
        requested_names = [cls._normalized_name(name) for name in root_names if cls._normalized_name(name)]
        if not requested_names:
            raise ValueError("At least one Shopware5 category root is required.")

        root_ids: list[str] = []
        missing_names: list[str] = []
        for name in requested_names:
            matches = [category_id for category_id, category in categories.items() if cls._normalized_name(category["name"]) == name]
            if not matches:
                missing_names.append(name)
                continue
            if len(matches) > 1:
                raise Shopware5APIError(f"Shopware5 category root '{name}' is ambiguous: {', '.join(matches)}.")
            root_ids.append(matches[0])
        if missing_names:
            raise Shopware5APIError("Shopware5 category roots not found: " + ", ".join(missing_names))
        return root_ids

    @classmethod
    def _snapshot_root_id(cls, *, snapshot: Shopware5CategoryMappingSnapshot, root_name: str) -> str:
        normalized_name = cls._normalized_name(root_name)
        matches = [
            root_id
            for root_id in snapshot.root_ids
            if cls._normalized_name(snapshot.categories[root_id]["name"]) == normalized_name
        ]
        if len(matches) != 1:
            raise Shopware5APIError(f"Shopware5 category root not found in preview: {root_name}.")
        return matches[0]

    @classmethod
    def _snapshot_category_id(
        cls,
        *,
        snapshot: Shopware5CategoryMappingSnapshot,
        root_id: str,
        category_name: str,
    ) -> str:
        normalized_name = cls._normalized_name(category_name)
        matches = [
            category_id
            for category_id, category in snapshot.categories.items()
            if cls._normalized_name(category["name"]) == normalized_name
            and cls._is_descendant_or_self(snapshot=snapshot, category_id=category_id, ancestor_id=root_id)
        ]
        if not matches:
            raise Shopware5APIError(
                f"Shopware5 category '{category_name}' was not found below root '{snapshot.categories[root_id]['name']}'."
            )
        if len(matches) > 1:
            paths = ", ".join(cls._category_path(snapshot=snapshot, category_id=category_id) for category_id in matches)
            raise Shopware5APIError(
                f"Shopware5 category '{category_name}' is ambiguous below root "
                f"'{snapshot.categories[root_id]['name']}': {paths}."
            )
        return matches[0]

    @staticmethod
    def _is_descendant_or_self(
        *,
        snapshot: Shopware5CategoryMappingSnapshot,
        category_id: str,
        ancestor_id: str,
    ) -> bool:
        current_id = category_id
        visited: set[str] = set()
        while current_id in snapshot.categories and current_id not in visited:
            if current_id == ancestor_id:
                return True
            visited.add(current_id)
            current_id = snapshot.categories[current_id]["parent_id"]
        return False

    @staticmethod
    def _category_path(*, snapshot: Shopware5CategoryMappingSnapshot, category_id: str) -> str:
        path: list[str] = []
        current_id = category_id
        visited: set[str] = set()
        while current_id in snapshot.categories and current_id not in visited:
            visited.add(current_id)
            category = snapshot.categories[current_id]
            path.append(category["name"])
            current_id = category["parent_id"]
        return " > ".join(reversed(path))

    @staticmethod
    def _scoped_categories(
        *,
        categories: dict[str, dict[str, Any]],
        root_ids: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        children_by_parent: dict[str, list[str]] = defaultdict(list)
        for category_id, category in categories.items():
            parent_id = category["parent_id"]
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

        return {category_id: categories[category_id] for category_id in selected_ids}

    @classmethod
    def _root_scoped_snapshot(
        cls,
        snapshot: Shopware5CategoryMappingSnapshot,
    ) -> Shopware5CategoryMappingSnapshot:
        """Exclude technical parents above the explicitly requested SW5 roots.

        Shopware 5 stores ``Deutsch`` and ``Schweiz`` below its internal
        ``Root`` category.  The local SW6 trees intentionally start at those
        two sales-channel roots, so the technical parent must never take part
        in local path matching, hierarchy updates, or reports.
        """
        categories = cls._scoped_categories(
            categories=snapshot.categories,
            root_ids=snapshot.root_ids,
        )
        if len(categories) == len(snapshot.categories):
            return snapshot
        return Shopware5CategoryMappingSnapshot(
            categories=categories,
            root_ids=tuple(root_id for root_id in snapshot.root_ids if root_id in categories),
            product_numbers_by_category={
                category_id: set(snapshot.product_numbers_by_category.get(category_id, set()))
                for category_id in categories
            },
            article_count=snapshot.article_count,
            article_detail_count=snapshot.article_detail_count,
        )

    @classmethod
    def _article_product_numbers(cls, article: dict[str, Any]) -> set[str]:
        detail_rows: list[dict[str, Any]] = []
        main_detail = article.get("mainDetail")
        if isinstance(main_detail, dict):
            detail_rows.append(main_detail)
        detail_rows.extend(cls._as_dict_list(article.get("details")))
        return {cls._text(detail.get("number")) for detail in detail_rows if cls._text(detail.get("number"))}

    @classmethod
    def _existing_categories(cls, snapshot: Shopware5CategoryMappingSnapshot) -> dict[str, Category]:
        remote_ids = set(snapshot.categories)
        local_categories = list(Category.objects.only("id", "name", "parent_id", "sw5_id", "sku"))
        by_sw5_id = {
            str(category.sw5_id): category
            for category in local_categories
            if category.sw5_id
            if str(category.sw5_id) in remote_ids
        }
        for category in local_categories:
            if category.sw5_id or not category.sku or category.sku not in remote_ids:
                continue
            if category.sku:
                by_sw5_id.setdefault(str(category.sku), category)

        claimed_category_ids = {category.pk for category in by_sw5_id.values()}
        categories_by_pk = {category.pk: category for category in local_categories}
        candidates_by_path: dict[tuple[str, ...], list[Category]] = defaultdict(list)
        for category in local_categories:
            if not category.sw5_id and category.pk not in claimed_category_ids:
                candidates_by_path[
                    cls._local_category_name_path(category=category, categories_by_pk=categories_by_pk)
                ].append(category)

        for sw5_id in cls._category_ids_in_parent_order(snapshot.categories):
            if sw5_id in by_sw5_id:
                continue
            candidates = [
                category
                for category in candidates_by_path.get(
                    cls._source_category_name_path(snapshot=snapshot, category_id=sw5_id),
                    [],
                )
                if category.pk not in claimed_category_ids
            ]
            if len(candidates) == 1:
                category = candidates[0]
                by_sw5_id[sw5_id] = category
                claimed_category_ids.add(category.pk)
        return by_sw5_id

    @classmethod
    def _source_category_name_path(
        cls,
        *,
        snapshot: Shopware5CategoryMappingSnapshot,
        category_id: str,
    ) -> tuple[str, ...]:
        path: list[str] = []
        current_id = category_id
        visited: set[str] = set()
        while current_id in snapshot.categories and current_id not in visited:
            visited.add(current_id)
            category = snapshot.categories[current_id]
            path.append(cls._normalized_name(category["name"]))
            current_id = category["parent_id"]
        return tuple(reversed(path))

    @classmethod
    def _local_category_name_path(
        cls,
        *,
        category: Category,
        categories_by_pk: dict[int, Category],
    ) -> tuple[str, ...]:
        path: list[str] = []
        current_category: Category | None = category
        visited: set[int] = set()
        while current_category is not None and current_category.pk not in visited:
            visited.add(current_category.pk)
            path.append(cls._normalized_name(current_category.name))
            current_category = categories_by_pk.get(current_category.parent_id)
        return tuple(reversed(path))

    @staticmethod
    def _category_ids_in_parent_order(categories: dict[str, dict[str, Any]]) -> list[str]:
        children_by_parent: dict[str, list[str]] = defaultdict(list)
        roots: list[str] = []
        for category_id, category in categories.items():
            parent_id = category["parent_id"]
            if parent_id in categories:
                children_by_parent[parent_id].append(category_id)
            else:
                roots.append(category_id)

        def sort_key(category_id: str) -> tuple[int, str, str]:
            category = categories[category_id]
            return category["position"], category["name"], category_id

        ordered_ids: list[str] = []
        pending = deque(sorted(roots, key=sort_key))
        while pending:
            category_id = pending.popleft()
            ordered_ids.append(category_id)
            pending.extend(sorted(children_by_parent.get(category_id, []), key=sort_key))
        return ordered_ids

    def _apply_assignments(
        self,
        *,
        snapshot: Shopware5CategoryMappingSnapshot,
        categories_by_sw5_id: dict[str, Category],
        replace_assignments: bool,
    ) -> dict[str, int]:
        category_ids = {category.pk for category in categories_by_sw5_id.values()}
        source_product_numbers = {
            product_number
            for product_numbers in snapshot.product_numbers_by_category.values()
            for product_number in product_numbers
        }
        products_by_erp_nr = Product.objects.in_bulk(source_product_numbers, field_name="erp_nr")
        desired_links = {
            (products_by_erp_nr[product_number].pk, categories_by_sw5_id[sw5_id].pk)
            for sw5_id, product_numbers in snapshot.product_numbers_by_category.items()
            for product_number in product_numbers
            if product_number in products_by_erp_nr
        }
        through_model = Product.categories.through
        existing_links = set(
            through_model.objects.filter(category_id__in=category_ids).values_list("product_id", "category_id")
        )
        new_links = desired_links - existing_links
        stale_links = existing_links - desired_links
        if new_links:
            through_model.objects.bulk_create(
                [
                    through_model(product_id=product_id, category_id=category_id)
                    for product_id, category_id in new_links
                ],
                ignore_conflicts=True,
            )
        if replace_assignments and stale_links:
            for product_id, category_id in stale_links:
                through_model.objects.filter(product_id=product_id, category_id=category_id).delete()

        return {
            "matched_products": len(products_by_erp_nr),
            "missing_products": len(source_product_numbers - set(products_by_erp_nr)),
            "created_assignments": len(new_links),
            "existing_assignments": len(existing_links & desired_links),
            "stale_assignments": len(stale_links),
            "removed_assignments": len(stale_links) if replace_assignments else 0,
        }

    def _category_reports(self, snapshot: Shopware5CategoryMappingSnapshot) -> list[dict[str, Any]]:
        def path_for(category_id: str) -> tuple[tuple[int, str], ...]:
            path: list[tuple[int, str]] = []
            current_id = category_id
            visited: set[str] = set()
            while current_id in snapshot.categories and current_id not in visited:
                visited.add(current_id)
                category = snapshot.categories[current_id]
                path.append((category["position"], category["name"]))
                current_id = category["parent_id"]
            return tuple(reversed(path))

        reports = []
        for category_id in sorted(snapshot.categories, key=path_for):
            category = snapshot.categories[category_id]
            reports.append(
                {
                    "id": category_id,
                    "name": category["name"],
                    "path": self._category_path(snapshot=snapshot, category_id=category_id),
                    "position": category["position"],
                    "active": category["active"],
                    "product_count": len(snapshot.product_numbers_by_category[category_id]),
                }
            )
        return reports

    @classmethod
    def _normalize_page_size(cls, page_size: int) -> int:
        try:
            normalized = int(page_size)
        except (TypeError, ValueError):
            normalized = cls.max_page_size
        return max(1, min(normalized, cls.max_page_size))

    @classmethod
    def _normalize_article_detail_workers(cls, workers: int) -> int:
        try:
            normalized = int(workers)
        except (TypeError, ValueError):
            normalized = 6
        return max(1, min(normalized, cls.max_article_detail_workers))

    @staticmethod
    def _as_dict_list(value: Any) -> list[dict[str, Any]]:
        return [item for item in (value or []) if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @classmethod
    def _normalized_name(cls, value: Any) -> str:
        return " ".join(cls._text(value).casefold().split())

    @staticmethod
    def _to_bool(value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _to_nonnegative_int(value: Any, *, default: int) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default
