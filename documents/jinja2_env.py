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


def _build_price_list_row(product, *, attributes: list[dict[str, str]] | None = None) -> dict:
    prices = list(getattr(product, "price_list_prices", []))
    price = prices[0] if prices else None
    return {
        "erp_nr": (product.erp_nr or "").strip() or "-",
        "name": (product.name or "").strip() or "Ohne Bezeichnung",
        "attributes": attributes if attributes is not None else _build_price_list_attribute_rows(product),
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


def _price_list_duplicate_categories(document) -> tuple:
    if not document or not document.pk or document.document_type != document.DocumentType.PRICE_LIST:
        return ()
    return tuple(
        document.price_list_duplicate_categories.filter(is_active=True).order_by("tree_id", "lft", "id")
    )


def _duplicate_category_for_path(category_path: list, duplicate_categories: tuple):
    category_ids = {category.pk for category in category_path}
    matches = [category for category in duplicate_categories if category.pk in category_ids]
    return max(matches, key=lambda category: (category.level, category.lft, category.pk), default=None)


def _variant_price_signature(product) -> tuple:
    """Return every value that is displayed in the price columns for a product."""
    prices = list(getattr(product, "price_list_prices", []))
    price = prices[0] if prices else None
    return (
        price.price if price else None,
        price.rebate_quantity if price else None,
        price.rebate_price if price else None,
        product.factor,
        (product.unit or "").strip(),
    )


def _build_price_list_variant_summaries(products: list) -> dict[int, dict]:
    """Map each variant-family member to a single representative price row.

    A family can have many concrete combinations (for example size, colour and
    print). The price list deliberately does not list those combinations. It
    emits one representative article per distinct set of displayed price and
    VPE values and combines the values of each variant attribute in that row.
    """
    from products.models import ProductVariantFamily
    from products.services import ProductVariantFamilyResolverService

    displayed_product_ids = {product.pk for product in products}
    if not displayed_product_ids:
        return {}

    products_by_id = {product.pk: product for product in products}
    summaries_by_product_id: dict[int, dict] = {}
    resolver = ProductVariantFamilyResolverService()
    families = ProductVariantFamily.objects.filter(
        is_active=True,
        default_product_id__in=displayed_product_ids,
    ).order_by("name", "id")
    for family in families:
        resolution = resolver.resolve(family)
        displayed_variants = tuple(
            variant for variant in resolution.variants if variant.product.pk in displayed_product_ids
        )
        if len(displayed_variants) < 2:
            continue
        default_variant = next(
            (variant for variant in displayed_variants if variant.product.pk == family.default_product_id),
            None,
        )
        if default_variant is None:
            continue
        family_product_ids = {variant.product.pk for variant in displayed_variants}
        if family_product_ids & summaries_by_product_id.keys():
            # A product must not be compressed by two overlapping families.
            # Families are deterministic by name and ID, so the first one wins.
            continue

        variants_by_price: dict[tuple, list] = {}
        for variant in displayed_variants:
            variants_by_price.setdefault(
                _variant_price_signature(products_by_id[variant.product.pk]),
                [],
            ).append(variant)

        representative_ids: set[int] = set()
        for price_variants in variants_by_price.values():
            ordered_variants = sorted(
                price_variants,
                key=lambda variant: (
                    variant.product.pk != family.default_product_id,
                    variant.product.erp_nr,
                    variant.product.pk,
                ),
            )
            representative = ordered_variants[0]
            representative_ids.add(representative.product.pk)
            attribute_rows = []
            for attribute_index, attribute in enumerate(resolution.attributes):
                value_names = []
                seen_value_ids: set[int] = set()
                for variant in ordered_variants:
                    value = variant.option_values[attribute_index]
                    if value.pk in seen_value_ids:
                        continue
                    seen_value_ids.add(value.pk)
                    value_names.append(value.name)
                attribute_rows.append(
                    {
                        "group": attribute.property_group.name,
                        "value": " - ".join(value_names),
                    }
                )
            summaries_by_product_id[representative.product.pk] = {
                "attributes": attribute_rows,
                "is_representative": True,
            }

        for product_id in family_product_ids - representative_ids:
            summaries_by_product_id[product_id] = {"is_representative": False}
    return summaries_by_product_id


def price_list_catalog_sections(
    root_level: int | None = None,
    active_only: bool = True,
    document=None,
) -> list[dict]:
    """Build the price list below each technical category root.

    The first category level (for example ``Deutsch/Schweiz``) is a technical
    sales-channel root and deliberately omitted.  Its children form the visible
    level 2 sections; their children form the visible level 3 product groups.
    Products below deeper levels receive a combined group name, for example
    ``Ringmappen - A4``. This preserves the visible level-3 grouping while
    making every further subcategory explicit in the price list.

    Products assigned directly to a visible level-2 category are deliberately
    omitted. Every listed product belongs to exactly one visible level-3 group;
    when it is assigned to several groups, the first category in tree order
    determines its one price-list position. Inactive visible categories are
    skipped completely. Categories selected on the price-list document are
    explicit exceptions and may additionally list the same article once per
    selected category subtree.

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
        categories__is_active=True,
        prices__sales_channel=default_sales_channel,
    )
    if active_only:
        product_queryset = product_queryset.filter(is_active=True)
    products = list(
        product_queryset.select_related("tax")
        .prefetch_related(
            Prefetch(
                "categories",
                queryset=Category.objects.filter(pk__in=category_ids, is_active=True).order_by(
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

    duplicate_categories = _price_list_duplicate_categories(document)
    variant_summaries = _build_price_list_variant_summaries(products)
    sections = []
    listed_product_ids: set[int] = set()
    listed_duplicate_category_product_ids: set[tuple[int, int]] = set()
    for root in root_categories:
        sections_by_id: dict[int, dict] = {}
        for product in products:
            variant_summary = variant_summaries.get(product.pk)
            if variant_summary and not variant_summary["is_representative"]:
                continue
            assigned_categories = [
                category
                for category in getattr(product, "price_list_categories", [])
                if (
                    category.tree_id == root.tree_id
                    and category.lft >= root.lft
                    and category.rght <= root.rght
                    and category.is_active
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
                # Ebene 1 ist der technische Verkaufskanal-Root, Ebene 2 nur
                # die Hauptüberschrift. Artikel werden erst ab Ebene 3 gelistet.
                if len(category_path) < 3 or not all(category.is_active for category in category_path[1:]):
                    continue

                duplicate_category = _duplicate_category_for_path(category_path, duplicate_categories)
                if duplicate_category:
                    duplicate_key = (product.pk, duplicate_category.pk)
                    if duplicate_key in listed_duplicate_category_product_ids:
                        continue
                elif product.pk in listed_product_ids:
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
                group["rows"].append(
                    _build_price_list_row(
                        product,
                        attributes=variant_summary["attributes"] if variant_summary else None,
                    )
                )
                if duplicate_category:
                    listed_duplicate_category_product_ids.add(duplicate_key)
                else:
                    listed_product_ids.add(product.pk)

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
    @jinja2.pass_context
    def price_list_catalog_sections_for_document(context, *args, **kwargs):
        kwargs.setdefault("document", context.get("document"))
        return price_list_catalog_sections(*args, **kwargs)

    env.globals.update(
        {
            "Product": Product,
            "Category": Category,
            "Tax": Tax,
            "price_list_catalog_sections": price_list_catalog_sections_for_document,
        }
    )
    return env
