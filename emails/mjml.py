from __future__ import annotations

import os
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


_jinja_env = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)
_jinja_env.filters["format_price"] = _format_price
_jinja_env.filters["format_date"] = _format_date
_jinja_env.filters["urlencode"] = lambda value: quote_plus(str(value or ""))


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
        return entry.price if entry else None

    @property
    def current_price(self) -> Decimal | None:
        return self.email_special_price or self.price

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
    def shipping_cost_is_free(self) -> bool:
        price = self.current_price
        return bool(price is not None and price >= Decimal("99.00"))

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


def _campaign_components(campaign: "EmailCampaign") -> list["EmailCampaignComponent"]:
    return list(
        campaign.components.filter(enabled=True)
        .select_related("library_component", "campaign_product__product")
        .order_by("order", "id")
    )


def _render_component_mjml(component: "EmailCampaignComponent", context: dict) -> str:
    markup = component.library_component.mjml_markup if component.library_component_id else ""
    if not markup:
        return ""

    component_context = {
        **context,
        **(getattr(component, "variables", None) or {}),
        "component": component,
    }

    if getattr(component, "campaign_product_id", None) and getattr(component, "campaign_product", None):
        cp = component.campaign_product
        sales_channel_ids = context.get("_sales_channel_ids", ())
        component_context["product"] = ProductEmailProxy(
            cp.product,
            special_price_override=cp.special_price_override,
            discount_pct=cp.discount_pct,
            sales_channel_ids=sales_channel_ids,
        )

    try:
        return _jinja_env.from_string(markup).render(component_context)
    except Exception:
        return ""


def render_campaign_mjml(campaign: "EmailCampaign") -> str:
    """Renders a campaign to a MJML string using Jinja2 component templates."""
    sales_channel_ids = _campaign_sales_channel_ids(campaign)

    products = [
        ProductEmailProxy(
            cp.product,
            special_price_override=cp.special_price_override,
            discount_pct=cp.discount_pct,
            sales_channel_ids=sales_channel_ids,
        )
        for cp in campaign.campaign_products.select_related("product").order_by("order", "id")
    ]

    base_context = {"products": products, "_sales_channel_ids": sales_channel_ids}
    components = _campaign_components(campaign)

    head_mjml = "\n".join(
        rendered
        for comp in components
        if getattr(getattr(comp, "library_component", None), "placement", "body") == "head"
        for rendered in [_render_component_mjml(comp, base_context)]
        if rendered.strip()
    )
    body_mjml = "\n".join(
        rendered
        for comp in components
        if getattr(getattr(comp, "library_component", None), "placement", "body") == "body"
        for rendered in [_render_component_mjml(comp, base_context)]
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
