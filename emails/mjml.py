from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable

from django.template.loader import render_to_string

if TYPE_CHECKING:
    from emails.models import EmailCampaign


class ProductEmailProxy:
    """Wraps a Product for template rendering, applying campaign-specific special_price_override."""

    def __init__(
        self,
        product,
        special_price_override: Decimal | None = None,
        sales_channel_ids: Iterable[int] | None = None,
    ):
        self._product = product
        self._override = special_price_override
        self._sales_channel_ids = tuple(sales_channel_ids or ())

    def __getattr__(self, name: str):
        return getattr(self._product, name)

    @property
    def email_special_price(self) -> Decimal | None:
        return self._override

    @property
    def price(self) -> Decimal | None:
        direct_price = getattr(self._product, "price", None)
        if direct_price is not None:
            return direct_price

        price_entry = self._get_price_entry()
        if price_entry is None:
            return None
        return price_entry.get_current_price(as_float=False)

    @property
    def discount_pct(self) -> int:
        list_price = self.price
        if not self._override or not list_price:
            return 0
        list_price = Decimal(str(list_price))
        if list_price <= 0:
            return 0
        return round((list_price - self._override) / list_price * 100)

    @property
    def shipping_cost_is_free(self) -> bool:
        try:
            return self._product.get_shipping_cost() == 0
        except AttributeError:
            price = self.email_special_price or self.price
            return bool(price and price >= Decimal("99.00"))

    def _get_price_entry(self):
        prices = getattr(self._product, "prices", None)
        if prices is None:
            return None

        queryset = prices.all()
        if self._sales_channel_ids:
            price_entry = (
                queryset.filter(sales_channel_id__in=self._sales_channel_ids)
                .order_by("-sales_channel__is_default", "sales_channel__name", "pk")
                .first()
            )
            if price_entry is not None:
                return price_entry

        price_entry = queryset.filter(sales_channel__is_default=True).order_by("pk").first()
        if price_entry is not None:
            return price_entry
        return queryset.order_by("pk").first()


def _campaign_sales_channel_ids(campaign: "EmailCampaign") -> tuple[int, ...]:
    return tuple(
        campaign.sales_channels.filter(enabled=True)
        .order_by("-sales_channel__is_default", "sales_channel__name", "pk")
        .values_list("sales_channel_id", flat=True)
    )


def render_campaign_mjml(campaign: "EmailCampaign") -> str:
    """Renders a campaign to a MJML string using Django template engine."""
    template_map = {
        "product": "emails/components/product.mjml",
        "product_shipping_free": "emails/components/product_shipping_free.mjml",
        "product_green": "emails/components/product.mjml",
    }
    order_form_map = {
        "product": "emails/components/order_form_product.mjml",
        "product_shipping_free": "emails/components/order_form_product_shipping_free.mjml",
        "product_green": "emails/components/order_form_product.mjml",
    }
    product_component = template_map.get(campaign.product_template, "emails/components/product.mjml")
    order_form_template = order_form_map.get(campaign.product_template, "emails/components/order_form_product.mjml")
    sales_channel_ids = _campaign_sales_channel_ids(campaign)

    proxies = [
        ProductEmailProxy(cp.product, cp.special_price_override, sales_channel_ids=sales_channel_ids)
        for cp in campaign.campaign_products.select_related("product").order_by("order", "id")
    ]

    context = {
        "h1": campaign.h1,
        "h1_small": campaign.h1_small,
        "intro_text": campaign.intro_text,
        "products": proxies,
        "product_component_template": product_component,
        "order_form_template": order_form_template,
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
