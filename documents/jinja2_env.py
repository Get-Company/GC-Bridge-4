import jinja2
from django.db.models import Prefetch


def _format_price_list_currency(value) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


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


def price_list_catalog_sections(root_level: int = 1, active_only: bool = True) -> list[dict]:
    from products.models import Category, Price, Product, ProductProperty

    root_categories = list(Category.objects.filter(level=root_level).order_by("sort_order", "lft", "name", "id"))
    if not root_categories and root_level != 0:
        root_categories = list(
            Category.objects.filter(parent__isnull=True).order_by("sort_order", "lft", "name", "id")
        )
    if not root_categories:
        return []

    subtree_categories = list(
        Category.objects.filter(
            tree_id__in={category.tree_id for category in root_categories},
            level__gte=min(category.level for category in root_categories),
        ).order_by("tree_id", "lft", "id")
    )
    subtree_category_ids = [category.pk for category in subtree_categories]
    product_queryset = Product.objects.filter(categories__in=subtree_category_ids)
    if active_only:
        product_queryset = product_queryset.filter(is_active=True)
    products = list(
        product_queryset.select_related("tax")
        .prefetch_related(
            Prefetch(
                "categories",
                queryset=Category.objects.filter(pk__in=subtree_category_ids).order_by("tree_id", "lft", "id"),
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
                queryset=Price.objects.order_by("price", "id"),
                to_attr="price_list_prices",
            ),
        )
        .order_by("erp_nr", "name", "id")
        .distinct()
    )

    products_by_category_id: dict[int, list] = {}
    for product in products:
        for category in getattr(product, "price_list_categories", []):
            products_by_category_id.setdefault(category.pk, []).append(product)

    sections = []
    for root in root_categories:
        categories = [
            category
            for category in subtree_categories
            if category.tree_id == root.tree_id and category.lft >= root.lft and category.rght <= root.rght
        ]
        groups = []
        for category in categories:
            if category.pk == root.pk:
                continue
            groups.append(
                {
                    "name": category.name or "Ohne Kategoriebezeichnung",
                    "rows": [
                        _build_price_list_row(product)
                        for product in products_by_category_id.get(category.pk, [])
                    ],
                }
            )
        sections.append(
            {
                "name": root.name or "Ohne Kategoriebezeichnung",
                "direct_rows": [
                    _build_price_list_row(product)
                    for product in products_by_category_id.get(root.pk, [])
                ],
                "groups": groups,
            }
        )
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
