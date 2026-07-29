from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction

from core.services import BaseService
from products.models import Category, Product


DEFAULT_CANONICAL_CATEGORY_ROOTS = ("Deutsch", "Schweiz")
DEFAULT_TECHNICAL_CATEGORY_ROOT = "Root"


class Shopware5DuplicateCategoryTreeError(RuntimeError):
    """The duplicate category trees cannot be merged safely."""


@dataclass(frozen=True, slots=True)
class CategoryTreePair:
    root_name: str
    relative_path: tuple[str, ...]
    duplicate: Category
    canonical: Category

    @property
    def display_path(self) -> str:
        return " > ".join(self.relative_path)


@dataclass(frozen=True, slots=True)
class CategoryTreeMergePlan:
    technical_root: Category
    duplicate_roots: tuple[Category, ...]
    pairs: tuple[CategoryTreePair, ...]
    missing_canonical_paths: tuple[tuple[str, tuple[str, ...]], ...]
    ambiguous_duplicate_paths: tuple[tuple[str, tuple[str, ...]], ...]
    ambiguous_canonical_paths: tuple[tuple[str, tuple[str, ...]], ...]


class Shopware5DuplicateCategoryTreeMergeService(BaseService):
    """Move SW5 IDs from an accidental ``Root`` duplicate to canonical roots.

    The service intentionally changes no names, parents, order values, or
    product relations.  Because ``Category.sw5_id`` is unique, every source
    ID is first cleared on the duplicate and then assigned to its canonical
    category in one database transaction.
    """

    model = Category

    def preview(
        self,
        *,
        root_names: Iterable[str] = DEFAULT_CANONICAL_CATEGORY_ROOTS,
        technical_root_name: str = DEFAULT_TECHNICAL_CATEGORY_ROOT,
    ) -> dict:
        plan = self._build_plan(root_names=root_names, technical_root_name=technical_root_name)
        transfers, skipped, conflicts = self._classify_pairs(plan.pairs)
        duplicate_category_ids = self._duplicate_category_ids(plan.duplicate_roots)
        duplicate_product_assignments = Product.categories.through.objects.filter(
            category_id__in=duplicate_category_ids
        ).count()
        return {
            "technical_root": self._category_label(plan.technical_root),
            "duplicate_roots": [self._category_label(category) for category in plan.duplicate_roots],
            "duplicate_categories": len(duplicate_category_ids),
            "duplicate_product_assignments": duplicate_product_assignments,
            "matched_categories": len(plan.pairs),
            "transfers": [self._pair_report(pair) for pair in transfers],
            "skipped_without_sw5_id": [self._pair_report(pair) for pair in skipped],
            "conflicts": [self._pair_report(pair) for pair in conflicts],
            "missing_canonical_paths": [self._path_report(root_name, path) for root_name, path in plan.missing_canonical_paths],
            "ambiguous_duplicate_paths": [
                self._path_report(root_name, path) for root_name, path in plan.ambiguous_duplicate_paths
            ],
            "ambiguous_canonical_paths": [
                self._path_report(root_name, path) for root_name, path in plan.ambiguous_canonical_paths
            ],
            "can_apply": not (
                conflicts
                or plan.missing_canonical_paths
                or plan.ambiguous_duplicate_paths
                or plan.ambiguous_canonical_paths
            ),
        }

    def apply(
        self,
        *,
        root_names: Iterable[str] = DEFAULT_CANONICAL_CATEGORY_ROOTS,
        technical_root_name: str = DEFAULT_TECHNICAL_CATEGORY_ROOT,
        delete_duplicate_subtrees: bool = False,
    ) -> dict:
        """Transfer SW5 IDs and optionally delete the now redundant branches."""
        plan = self._build_plan(root_names=root_names, technical_root_name=technical_root_name)
        transfers, _, conflicts = self._classify_pairs(plan.pairs)
        self._ensure_plan_is_safe(plan=plan, conflicts=conflicts)

        with transaction.atomic():
            duplicate_ids = [pair.duplicate.pk for pair in transfers]
            if duplicate_ids:
                Category.objects.filter(pk__in=duplicate_ids).update(sw5_id=None)
            for pair in transfers:
                Category.objects.filter(pk=pair.canonical.pk).update(sw5_id=pair.duplicate.sw5_id)

            deleted_categories = 0
            technical_root_deleted = False
            if delete_duplicate_subtrees:
                for duplicate_root in plan.duplicate_roots:
                    deleted_categories += self._subtree_size(duplicate_root)
                    duplicate_root.delete()
                if not Category.objects.filter(parent_id=plan.technical_root.pk).exists():
                    plan.technical_root.delete()
                    deleted_categories += 1
                    technical_root_deleted = True

        return {
            "transferred_sw5_ids": len(transfers),
            "cleared_duplicate_sw5_ids": len(transfers),
            "deleted_categories": deleted_categories,
            "technical_root_deleted": technical_root_deleted,
        }

    def _build_plan(
        self,
        *,
        root_names: Iterable[str],
        technical_root_name: str,
    ) -> CategoryTreeMergePlan:
        normalized_root_names = self._normalized_root_names(root_names)
        technical_root = self._single_category(
            Category.objects.filter(parent__isnull=True),
            name=technical_root_name,
            description="technische Root-Kategorie",
        )

        duplicate_roots: list[Category] = []
        pairs: list[CategoryTreePair] = []
        missing_canonical_paths: list[tuple[str, tuple[str, ...]]] = []
        ambiguous_duplicate_paths: list[tuple[str, tuple[str, ...]]] = []
        ambiguous_canonical_paths: list[tuple[str, tuple[str, ...]]] = []

        for root_name in normalized_root_names:
            duplicate_root = self._single_category(
                Category.objects.filter(parent_id=technical_root.pk),
                name=root_name,
                description=f"duplizierte Kategorie unter {technical_root.name}",
            )
            canonical_root = self._single_category(
                Category.objects.filter(parent__isnull=True),
                name=root_name,
                description="kanonische Root-Kategorie",
            )
            duplicate_roots.append(duplicate_root)

            duplicate_by_path = self._categories_by_relative_path(duplicate_root)
            canonical_by_path = self._categories_by_relative_path(canonical_root)
            for path, categories in duplicate_by_path.items():
                if len(categories) > 1:
                    ambiguous_duplicate_paths.append((root_name, path))
                    continue
                canonical_categories = canonical_by_path.get(path, [])
                if not canonical_categories:
                    missing_canonical_paths.append((root_name, path))
                    continue
                if len(canonical_categories) > 1:
                    ambiguous_canonical_paths.append((root_name, path))
                    continue
                pairs.append(
                    CategoryTreePair(
                        root_name=root_name,
                        relative_path=path,
                        duplicate=categories[0],
                        canonical=canonical_categories[0],
                    )
                )

        return CategoryTreeMergePlan(
            technical_root=technical_root,
            duplicate_roots=tuple(duplicate_roots),
            pairs=tuple(pairs),
            missing_canonical_paths=tuple(missing_canonical_paths),
            ambiguous_duplicate_paths=tuple(ambiguous_duplicate_paths),
            ambiguous_canonical_paths=tuple(ambiguous_canonical_paths),
        )

    @classmethod
    def _classify_pairs(
        cls,
        pairs: Iterable[CategoryTreePair],
    ) -> tuple[list[CategoryTreePair], list[CategoryTreePair], list[CategoryTreePair]]:
        transfers: list[CategoryTreePair] = []
        skipped: list[CategoryTreePair] = []
        conflicts: list[CategoryTreePair] = []
        for pair in pairs:
            duplicate_sw5_id = cls._text(pair.duplicate.sw5_id)
            canonical_sw5_id = cls._text(pair.canonical.sw5_id)
            if not duplicate_sw5_id:
                skipped.append(pair)
            elif canonical_sw5_id and canonical_sw5_id != duplicate_sw5_id:
                conflicts.append(pair)
            elif canonical_sw5_id == duplicate_sw5_id:
                skipped.append(pair)
            else:
                transfers.append(pair)
        return transfers, skipped, conflicts

    @classmethod
    def _ensure_plan_is_safe(
        cls,
        *,
        plan: CategoryTreeMergePlan,
        conflicts: list[CategoryTreePair],
    ) -> None:
        messages: list[str] = []
        if plan.missing_canonical_paths:
            messages.append(
                "fehlende kanonische Pfade: "
                + ", ".join(cls._display_path(root_name, path) for root_name, path in plan.missing_canonical_paths)
            )
        if plan.ambiguous_duplicate_paths:
            messages.append(
                "mehrdeutige Duplikatpfade: "
                + ", ".join(
                    cls._display_path(root_name, path) for root_name, path in plan.ambiguous_duplicate_paths
                )
            )
        if plan.ambiguous_canonical_paths:
            messages.append(
                "mehrdeutige kanonische Pfade: "
                + ", ".join(
                    cls._display_path(root_name, path) for root_name, path in plan.ambiguous_canonical_paths
                )
            )
        if conflicts:
            messages.append(
                "abweichende kanonische SW5-IDs: " + ", ".join(pair.display_path for pair in conflicts)
            )
        if messages:
            raise Shopware5DuplicateCategoryTreeError(
                "Der Duplikatbaum wurde nicht verändert: " + "; ".join(messages) + "."
            )

    @classmethod
    def _categories_by_relative_path(cls, root: Category) -> dict[tuple[str, ...], list[Category]]:
        nodes = [root, *root.get_descendants().only("id", "name", "parent_id", "sw5_id")]
        nodes_by_id = {category.pk: category for category in nodes}
        paths: dict[tuple[str, ...], list[Category]] = defaultdict(list)
        for category in nodes:
            path: list[str] = []
            current_category: Category | None = category
            visited: set[int] = set()
            while current_category is not None and current_category.pk not in visited:
                visited.add(current_category.pk)
                path.append(cls._text(current_category.name))
                if current_category.pk == root.pk:
                    break
                current_category = nodes_by_id.get(current_category.parent_id)
            if not current_category or current_category.pk != root.pk:
                raise Shopware5DuplicateCategoryTreeError(
                    f"Kategorie {category.pk} liegt nicht vollstaendig unter {root.name}."
                )
            paths[tuple(reversed(path))].append(category)
        return paths

    @staticmethod
    def _duplicate_category_ids(roots: Iterable[Category]) -> list[int]:
        category_ids: list[int] = []
        for root in roots:
            category_ids.extend(root.get_descendants(include_self=True).values_list("pk", flat=True))
        return category_ids

    @staticmethod
    def _subtree_size(root: Category) -> int:
        return root.get_descendants(include_self=True).count()

    @classmethod
    def _single_category(cls, queryset, *, name: str, description: str) -> Category:
        categories = list(queryset.filter(name__iexact=cls._text(name)).only("id", "name", "parent_id", "sw5_id"))
        if len(categories) != 1:
            raise Shopware5DuplicateCategoryTreeError(
                f"{description} '{name}' wurde {len(categories)}-mal gefunden; erwartet wird genau eine Kategorie."
            )
        return categories[0]

    @classmethod
    def _normalized_root_names(cls, root_names: Iterable[str]) -> tuple[str, ...]:
        names = tuple(cls._text(name) for name in root_names if cls._text(name))
        if not names:
            raise Shopware5DuplicateCategoryTreeError("Mindestens eine kanonische Root-Kategorie ist erforderlich.")
        normalized_names = [name.casefold() for name in names]
        if len(set(normalized_names)) != len(normalized_names):
            raise Shopware5DuplicateCategoryTreeError("Jede kanonische Root-Kategorie darf nur einmal angegeben werden.")
        return names

    @staticmethod
    def _text(value: object) -> str:
        return "" if value is None else str(value).strip()

    @classmethod
    def _pair_report(cls, pair: CategoryTreePair) -> dict:
        return {
            "path": pair.display_path,
            "duplicate_id": pair.duplicate.pk,
            "duplicate_sw5_id": cls._text(pair.duplicate.sw5_id),
            "canonical_id": pair.canonical.pk,
            "canonical_sw5_id": cls._text(pair.canonical.sw5_id),
        }

    @classmethod
    def _path_report(cls, root_name: str, path: tuple[str, ...]) -> str:
        return cls._display_path(root_name, path)

    @staticmethod
    def _display_path(root_name: str, path: tuple[str, ...]) -> str:
        return f"{root_name}: {' > '.join(path)}"

    @classmethod
    def _category_label(cls, category: Category) -> str:
        return f"[{category.pk}] {category.name}"
