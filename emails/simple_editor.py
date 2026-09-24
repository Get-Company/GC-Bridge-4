"""Fixed newsletter layout and the small set of fields exposed by its editor."""
from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote_plus, urlparse
from uuid import UUID

from django.template.defaultfilters import strip_tags
from django.template.loader import render_to_string

from emails.mjml import ProductEmailProxy, _campaign_sales_channel_ids


DEFAULT_CONTENT = {
    "headline": "Immer klaren Durchblick",
    "subheadline": ".... für den Büro-Alltag mit Papier",
    "salutation": "Hallo",
    "intro": (
        "Egal ob wirkungsvoll gestaltetes Titelblatt oder ob Sie wichtige Daten "
        "auf Ihren Akten sofort erkennen möchten: Mit transparenten "
        "Ordnungs-Mappen behalten Sie den Überblick.\n\n"
        "Mehr Transparenz und immer klaren Durchblick – so macht das Arbeiten "
        "mit dem Classei-System rund um den Schreibtisch noch mehr Spaß."
    ),
    "product_heading": "Unsere Produktauswahl",
    "order_heading": "Bestellformular",
    "order_text": "Einfach auf diese E-Mail antworten und die gewünschte Anzahl eingeben.",
    "order_phone": "oder schnell anrufen:\n+49 (0)8641 97 59 0",
    "logo_url": (
        "https://www.classei.de/index.php?option=com_joomgallery&view=image"
        "&format=raw&id=355&type=orig"
    ),
    "product_texts": {},
    "headings": [],
}


def normalize_headings(value):
    """Keep editor headings small, unique and safe for MJML CSS class names."""
    if not isinstance(value, list):
        return []
    headings = []
    seen = set()
    for item in value[:30]:
        if not isinstance(item, dict):
            continue
        try:
            identifier = str(UUID(str(item.get("id", ""))))
        except (ValueError, TypeError, AttributeError):
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        headings.append({
            "id": identifier,
            "after_product_id": str(item.get("after_product_id") or ""),
            "title": str(item.get("title") or "")[:255],
            "center_text": str(item.get("center_text") or "")[:2000],
            "right_text": str(item.get("right_text") or "")[:2000],
        })
    return headings


def content_for(campaign, override=None):
    content = {**DEFAULT_CONTENT, **(campaign.editor_content or {})}
    if isinstance(override, dict):
        content.update({key: value for key, value in override.items() if key in DEFAULT_CONTENT})
    if not isinstance(content.get("product_texts"), dict):
        content["product_texts"] = {}
    content["headings"] = normalize_headings(content.get("headings"))
    if not valid_media_url(content.get("logo_url", "")):
        content["logo_url"] = DEFAULT_CONTENT["logo_url"]
    return content


def valid_media_url(value):
    parsed = urlparse(str(value).strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _price(value):
    return f"{Decimal(str(value)):.2f}".replace(".", ",") if value is not None else ""


def _media_urls(product, override):
    if override.get("media_urls"):
        return [
            url.strip() for url in str(override["media_urls"]).splitlines()
            if valid_media_url(url)
        ]
    return [image.url for image in product.get_images() if image.url]


def offer_for_product(campaign_product, content, sales_channel_ids):
    product = campaign_product.product
    proxy = ProductEmailProxy(
        product,
        special_price_override=campaign_product.special_price_override,
        discount_pct=campaign_product.discount_pct,
        sales_channel_ids=sales_channel_ids,
    )
    custom = content["product_texts"].get(str(product.pk), {})
    if not isinstance(custom, dict):
        custom = {}
    return {
            "id": campaign_product.pk,
            "section_heading": custom.get("section_heading", ""),
            "title": custom.get("title") or product.name or product.erp_nr,
            "description": custom.get("description") or strip_tags(product.description_short or ""),
            "sku": product.erp_nr,
            "url": f"https://www.classei-shop.com/search?sSearch={quote_plus(product.erp_nr)}",
            "images": _media_urls(product, custom),
            "list_price": _price(proxy.price),
            "current_price": _price(proxy.current_price),
            "has_special": proxy.email_special_price is not None,
            "discount_pct": proxy.discount_pct,
            "unit": f"{product.factor} St." if product.factor and product.factor > 0 else product.unit or "St.",
            "min_purchase": product.min_purchase,
            "purchase_unit": product.purchase_unit,
            "shipping_free": proxy.shipping_cost_is_free,
            "headings_after": [],
    }


def build_simple_mjml(campaign, *, recipient=None, override=None):
    content = content_for(campaign, override)
    sales_channel_ids = _campaign_sales_channel_ids(campaign)
    offers = [
        offer_for_product(item, content, sales_channel_ids)
        for item in campaign.campaign_products.select_related("product").order_by("order", "id")
    ]
    headings_by_product = {str(offer["id"]): offer["headings_after"] for offer in offers}
    intro_headings = []
    tail_headings = []
    for heading in content["headings"]:
        after_id = heading["after_product_id"]
        if not after_id:
            intro_headings.append(heading)
        elif after_id in headings_by_product:
            headings_by_product[after_id].append(heading)
        else:
            tail_headings.append(heading)
    recipient_name = getattr(recipient, "full_name", "") if recipient else ""
    return render_to_string("emails/simple_newsletter.mjml", {
        "content": content,
        "offers": offers,
        "intro_headings": intro_headings,
        "tail_headings": tail_headings,
        "recipient_name": recipient_name or "...",
    })
