import jinja2
from django.db.models import Prefetch


def _format_price_list_currency(value) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _format_price_list_quantity(value) -> str:
    if value in (None, "", 0):
        return "-"
    return str(value)


def _build_price_list_vpe_display(product) -> str:
    factor = product.factor
    unit = (product.unit or "").strip()
    if factor and unit:
        return f"{factor} {unit}"
    if factor:
        return str(factor)
    if unit:
        return unit
    return "-"


def _build_price_list_attribute_rows(product) -> list[dict[str, str]]:
    rows = []
    for product_property in getattr(product, "price_list_properties", []):
        value = product_property.value
        group = value.group if value and value.group_id else None
        value_name = (value.name or "").strip() if value else ""
        if value_name:
            rows.append(
                {
                    "group": (group.name or "").strip() if group else "",
                    "value": value_name,
                }
            )
    return rows


def _build_price_list_row(product) -> dict:
    prices = list(getattr(product, "price_list_prices", []))
    price = prices[0] if prices else None
    return {
        "erp_nr": (product.erp_nr or "").strip() or "-",
        "name": (product.name or "").strip() or "Ohne Bezeichnung",
        "attributes": _build_price_list_attribute_rows(product),
        "factor": product.factor,
        "vpe_display": _build_price_list_vpe_display(product),
        "price_display": _format_price_list_currency(price.price if price else None),
        "rebate_quantity_display": _format_price_list_quantity(price.rebate_quantity if price else None),
        "rebate_price_display": _format_price_list_currency(price.rebate_price if price else None),
    }


def _category_sort_key(category) -> tuple:
    return (
        category.tree_id,
        category.lft,
        category.sort_order,
        (category.name or "").lower(),
        category.pk,
    )


def _category_path_from_root(category, root, categories_by_id: dict[int, object]) -> list:
    path = []
    current = category
    while current is not None:
        path.append(current)
        if current.pk == root.pk:
            return list(reversed(path))
        current = categories_by_id.get(current.parent_id)
    return []


def _is_category_below(category, possible_parent) -> bool:
    return (
        category.tree_id == possible_parent.tree_id
        and category.lft > possible_parent.lft
        and category.rght < possible_parent.rght
    )


def price_list_catalog_sections(root_level: int | None = None, active_only: bool = True) -> list[dict]:
    """Build the price list below each technical category root.

    The first category level (for example ``Deutsch/Schweiz``) is a technical
    sales-channel root and deliberately omitted.  Its children form the visible
    level 2 sections; their children form the visible level 3 product groups.
    Products below deeper levels receive a combined group name, for example
    ``Ringmappen - A4``. This preserves the visible level-3 grouping while
    making every further subcategory explicit in the price list.

    ``root_level`` is accepted for existing document templates but intentionally
    ignored: the root is always the actual MPTT root so the output structure is
    consistent for every sales-channel tree.
    """
    from products.models import Category, Price, Product, ProductProperty
    from shopware.models import ShopwareSettings

    del root_level
    default_sales_channel = (
        ShopwareSettings.objects.filter(is_active=True, is_default=True).order_by("pk").first()
    )
    if default_sales_channel is None:
        return []

    root_categories = list(
        Category.objects.filter(parent__isnull=True).order_by("tree_id", "lft", "sort_order", "name", "id")
    )
    if not root_categories:
        return []

    categories = list(
        Category.objects.filter(tree_id__in={category.tree_id for category in root_categories}).order_by(
            "tree_id", "lft", "sort_order", "name", "id"
        )
    )
    category_ids = [category.pk for category in categories]
    categories_by_id = {category.pk: category for category in categories}

    product_queryset = Product.objects.filter(
        categories__in=category_ids,
        prices__sales_channel=default_sales_channel,
    )
    if active_only:
        product_queryset = product_queryset.filter(is_active=True)
    products = list(
        product_queryset.select_related("tax")
        .prefetch_related(
            Prefetch(
                "categories",
                queryset=Category.objects.filter(pk__in=category_ids).order_by(
                    "tree_id", "lft", "sort_order", "name", "id"
                ),
                to_attr="price_list_categories",
            ),
            Prefetch(
                "product_properties",
                queryset=ProductProperty.objects.select_related("value__group").order_by(
                    "value__group__name",
                    "value__name",
                ),
                to_attr="price_list_properties",
            ),
            Prefetch(
                "prices",
                queryset=Price.objects.filter(sales_channel=default_sales_channel).order_by("id"),
                to_attr="price_list_prices",
            ),
        )
        .order_by("sort_order", "erp_nr", "name", "id")
        .distinct()
    )

    sections = []
    for root in root_categories:
        sections_by_id: dict[int, dict] = {}
        for product in products:
            assigned_categories = [
                category
                for category in getattr(product, "price_list_categories", [])
                if (
                    category.tree_id == root.tree_id
                    and category.lft >= root.lft
                    and category.rght <= root.rght
                )
            ]
            leaf_categories = [
                category
                for category in assigned_categories
                if not any(
                    other_category.pk != category.pk and _is_category_below(other_category, category)
                    for other_category in assigned_categories
                )
            ]
            for leaf_category in leaf_categories:
                category_path = _category_path_from_root(leaf_category, root, categories_by_id)
                if len(category_path) < 2:
                    continue

                section_category = category_path[1]
                section = sections_by_id.setdefault(
                    section_category.pk,
                    {
                        "name": section_category.name or "Ohne Kategoriebezeichnung",
                        "sort_key": _category_sort_key(section_category),
                        "direct_rows": [],
                        "groups_by_path": {},
                    },
                )
                row = _build_price_list_row(product)
                if len(category_path) == 2:
                    section["direct_rows"].append(row)
                    continue

                group_categories = category_path[2:]
                group_key = tuple(category.pk for category in group_categories)
                group = section["groups_by_path"].setdefault(
                    group_key,
                    {
                        "name": " - ".join(
                            category.name or "Ohne Kategoriebezeichnung"
                            for category in group_categories
                        ),
                        "sort_key": tuple(_category_sort_key(category) for category in group_categories),
                        "rows": [],
                    },
                )
                group["rows"].append(row)

        for section in sorted(sections_by_id.values(), key=lambda item: item["sort_key"]):
            section["direct_rows"].sort(key=lambda row: (row["erp_nr"], row["name"]))
            section["groups"] = sorted(
                section.pop("groups_by_path").values(),
                key=lambda item: item["sort_key"],
            )
            for group in section["groups"]:
                group["rows"].sort(key=lambda row: (row["erp_nr"], row["name"]))
                group.pop("sort_key")
            section.pop("sort_key")
            sections.append(section)
    return sections


def build_env() -> jinja2.Environment:
    from products.models import Category, Product, Tax

    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(["html", "htm"]),
        undefined=jinja2.Undefined,
        keep_trailing_newline=True,
    )
    env.globals.update(
        {
            "Product": Product,
            "Category": Category,
            "Tax": Tax,
            "price_list_catalog_sections": price_list_catalog_sections,
        }
    )
    return env
