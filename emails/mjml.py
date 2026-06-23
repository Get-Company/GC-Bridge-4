from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal, ROUND_UP
from typing import TYPE_CHECKING, Iterable
from urllib.parse import quote_plus

import jinja2
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from emails.models import EmailCampaign, EmailCampaignComponent


def _format_price(value, decimals: int = 2) -> str:
    if value is None:
        return ""
    return f"{Decimal(str(value)):.{decimals}f}"


def _format_date(value, date_format: str = "%d.%m.%Y") -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime(date_format)
    return str(value)


def _round_up_5ct(value: Decimal) -> Decimal:
    step = Decimal("0.05")
    return (Decimal(value) / step).to_integral_value(rounding=ROUND_UP) * step


def _decimal_as_float(value, *, as_float: bool = False):
    if value is None:
        return None
    return float(value) if as_float else value


_jinja_env = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)
_jinja_env.filters["format_price"] = _format_price
_jinja_env.filters["format_date"] = _format_date
_jinja_env.filters["urlencode"] = lambda value: quote_plus(str(value or ""))

_HYPHENATED_PLACEHOLDER_RE = re.compile(
    r"(\{\{\s*)([A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+)(?=\s*(?:\||\}\}))"
)


class ProductEmailProxy:
    """Wraps a Product + campaign price override for Jinja2 MJML template rendering."""

    def __init__(
        self,
        product,
        special_price_override: Decimal | None = None,
        discount_pct: Decimal | None = None,
        sales_channel_ids: Iterable[int] | None = None,
    ):
        self._product = product
        self._override = special_price_override
        self._discount_pct = discount_pct
        self._sales_channel_ids = tuple(sales_channel_ids or ())

    def __getattr__(self, name: str):
        return getattr(self._product, name)

    @property
    def email_special_price(self) -> Decimal | None:
        if self._override is not None:
            return self._override
        entry = self._get_price_entry()
        if entry is not None and hasattr(entry, "get_special_price"):
            special_price = entry.get_special_price(as_float=False)
            if special_price is not None:
                return special_price
        if self._discount_pct is None:
            return None
        list_price = self.price
        if list_price is None:
            return None
        return _round_up_5ct(
            list_price * (Decimal("100") - Decimal(str(self._discount_pct))) / Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def price(self) -> Decimal | None:
        entry = self._get_price_entry()
        if not entry:
            return None
        if hasattr(entry, "get_standard_price"):
            return entry.get_standard_price(as_float=False)
        return entry.price

    @property
    def current_price(self) -> Decimal | None:
        special_price = self.email_special_price
        if special_price is not None:
            return special_price
        entry = self._get_price_entry()
        if entry is not None and hasattr(entry, "get_current_price"):
            return entry.get_current_price(as_float=False)
        return self.price

    @property
    def discount_pct(self) -> int:
        if self._discount_pct is not None:
            return round(Decimal(str(self._discount_pct)))
        list_price = self.price
        special_price = self.email_special_price
        if not special_price or not list_price or list_price <= 0:
            return 0
        return round((list_price - special_price) / list_price * 100)

    @property
    def special_end_date(self):
        entry = self._get_price_entry()
        if entry is None:
            return None
        return getattr(entry, "special_end_date", None)

    @property
    def shipping_cost_is_free(self) -> bool:
        price = self.current_price
        return bool(price is not None and price >= Decimal("99.00"))

    def get_current_price(self, *, as_float: bool = False):
        return _decimal_as_float(self.current_price, as_float=as_float)

    def get_list_price(self, *, as_float: bool = False):
        return _decimal_as_float(self.price, as_float=as_float)

    def get_special_price(self, *, as_float: bool = False):
        return _decimal_as_float(self.email_special_price, as_float=as_float)

    def get_shipping_cost(self):
        return 0 if self.shipping_cost_is_free else None

    @property
    def images(self):
        return self._product.get_images()

    @property
    def first_image(self):
        images = self.images
        return images[0] if images else None

    def _get_price_entry(self):
        prices = getattr(self._product, "prices", None)
        if prices is None:
            return None
        queryset = prices.all()
        if self._sales_channel_ids:
            entry = (
                queryset.filter(sales_channel_id__in=self._sales_channel_ids)
                .order_by("-sales_channel__is_default", "pk")
                .first()
            )
            if entry:
                return entry
        entry = queryset.filter(sales_channel__is_default=True).order_by("pk").first()
        return entry or queryset.order_by("pk").first()


def _campaign_sales_channel_ids(campaign: "EmailCampaign") -> tuple[int, ...]:
    from shopware.models import ShopwareSettings
    default = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
    if default:
        return (default.pk,)
    return ()


def campaign_offer_context(products: Iterable[ProductEmailProxy]) -> dict:
    special_end_dates = []
    special_price = False
    for product in products:
        if product.email_special_price is None:
            continue
        special_price = True
        special_end_date = product.special_end_date
        if special_end_date is not None:
            special_end_dates.append(special_end_date)
    offer_valid_until = max(special_end_dates) if special_end_dates else None
    offer_valid_until_date = _format_date(offer_valid_until)
    offer_valid_until_text = (
        f"Angebot gültig bis {offer_valid_until_date}"
        if special_price and offer_valid_until_date
        else ""
    )
    return {
        "special_price": special_price,
        "special_end_date": offer_valid_until,
        "offer_valid_until": offer_valid_until,
        "offer_valid_until_date": offer_valid_until_date,
        "offer_valid_until_text": offer_valid_until_text,
    }


def _campaign_components(campaign: "EmailCampaign") -> list["EmailCampaignComponent"]:
    return list(
        campaign.components.filter(enabled=True)
        .select_related("library_component", "product", "campaign_product__product", "parent")
        .order_by("order", "id")
    )


def _normalize_hyphenated_placeholders(markup: str) -> str:
    return _HYPHENATED_PLACEHOLDER_RE.sub(
        lambda match: f'{match.group(1)}__component_variables["{match.group(2)}"]',
        markup,
    )


def _component_identity(component: "EmailCampaignComponent") -> int:
    return getattr(component, "pk", None) or getattr(component, "id", None) or id(component)


def _component_parent_id(component: "EmailCampaignComponent") -> int | None:
    parent_id = getattr(component, "parent_id", None)
    if parent_id is not None:
        return parent_id
    parent = getattr(component, "parent", None)
    return _component_identity(parent) if parent is not None else None


def _component_children_map(
    components: list["EmailCampaignComponent"],
) -> dict[int | None, list["EmailCampaignComponent"]]:
    child_map: dict[int | None, list["EmailCampaignComponent"]] = {}
    component_ids = {_component_identity(component) for component in components}

    for component in components:
        parent_id = _component_parent_id(component)
        if parent_id not in component_ids:
            parent_id = None
        child_map.setdefault(parent_id, []).append(component)

    return child_map


def _render_component_children(
    component: "EmailCampaignComponent",
    context: dict,
    child_map: dict[int | None, list["EmailCampaignComponent"]],
    seen: set[int],
) -> str:
    return "\n".join(
        rendered
        for child in child_map.get(_component_identity(component), [])
        for rendered in [_render_component_mjml(child, context, child_map, seen)]
        if rendered.strip()
    )


def _render_component_mjml(
    component: "EmailCampaignComponent",
    context: dict,
    child_map: dict[int | None, list["EmailCampaignComponent"]] | None = None,
    seen: set[int] | None = None,
) -> str:
    component_id = _component_identity(component)
    seen = set(seen or ())
    if component_id in seen:
        return ""
    seen.add(component_id)

    markup = component.library_component.mjml_markup if component.library_component_id else ""
    if not markup:
        return ""

    library_component = getattr(component, "library_component", None)
    default_variables = getattr(library_component, "default_variables", None) or {}
    component_variables = {
        **default_variables,
        **(getattr(component, "variables", None) or {}),
    }
    component_context = {
        **context,
        **component_variables,
        "__component_variables": component_variables,
        "variables": component_variables,
        "component": component,
    }

    product = getattr(component, "product", None)
    if product is None and getattr(component, "campaign_product_id", None) and getattr(component, "campaign_product", None):
        cp = component.campaign_product
        product = cp.product

    if product is not None:
        sales_channel_ids = context.get("_sales_channel_ids", ())
        component_context["product"] = ProductEmailProxy(
            product,
            sales_channel_ids=sales_channel_ids,
        )

    child_map = child_map or {}
    component_context["children"] = _render_component_children(
        component,
        component_context,
        child_map,
        seen,
    )

    try:
        return _jinja_env.from_string(_normalize_hyphenated_placeholders(markup)).render(
            component_context
        )
    except Exception:
        return ""


def render_campaign_mjml(campaign: "EmailCampaign") -> str:
    """Renders a campaign to a MJML string using Jinja2 component templates."""
    sales_channel_ids = _campaign_sales_channel_ids(campaign)

    components = _campaign_components(campaign)
    products = []
    for component in components:
        product = getattr(component, "product", None)
        if product is None and getattr(component, "campaign_product_id", None) and getattr(component, "campaign_product", None):
            product = component.campaign_product.product
        if product is not None:
            products.append(
                ProductEmailProxy(
                    product,
                    sales_channel_ids=sales_channel_ids,
                )
            )

    base_context = {
        "products": products,
        "_sales_channel_ids": sales_channel_ids,
        **campaign_offer_context(products),
    }
    child_map = _component_children_map(components)

    head_mjml = "\n".join(
        rendered
        for comp in child_map.get(None, [])
        if getattr(getattr(comp, "library_component", None), "placement", "body") == "head"
        for rendered in [_render_component_mjml(comp, base_context, child_map)]
        if rendered.strip()
    )
    body_mjml = "\n".join(
        rendered
        for comp in child_map.get(None, [])
        if getattr(getattr(comp, "library_component", None), "placement", "body") == "body"
        for rendered in [_render_component_mjml(comp, base_context, child_map)]
        if rendered.strip()
    )

    context = {
        **base_context,
        "head_mjml": head_mjml,
        "body_mjml": body_mjml,
    }
    return render_to_string("emails/newsletter_base.mjml", context)


def compile_mjml_to_html(mjml_string: str) -> str:
    """Compiles a MJML string to HTML using the MJML CLI."""
    with tempfile.NamedTemporaryFile(suffix=".mjml", mode="w", encoding="utf-8", delete=False) as f:
        f.write(mjml_string)
        tmp_mjml = f.name

    out_html = tmp_mjml.replace(".mjml", ".html")
    try:
        command = ["mjml", tmp_mjml, "-o", out_html]
        if shutil.which("mjml") is None:
            command = ["npx", "mjml", tmp_mjml, "-o", out_html]

        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        with open(out_html, encoding="utf-8") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_mjml):
            os.unlink(tmp_mjml)
        if os.path.exists(out_html):
            os.unlink(out_html)
