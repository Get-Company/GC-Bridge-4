"""Read-only MJML renderer for campaigns saved with the retired visual editor."""
from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse
from uuid import UUID

from django.template.loader import render_to_string


RECIPIENT_FIELDS = {
    "full_name", "first_name", "last_name", "email",
    "salutation_display_name", "salutation_letter_name", "street", "zip_code", "city",
}
RECIPIENT_TOKEN = re.compile(r"\{\{\s*recipient\.([a-z_]+)\s*\}\}")


def merge_recipient_text(value, recipient):
    def replace(match):
        field = match.group(1)
        if field not in RECIPIENT_FIELDS:
            return match.group(0)
        if recipient is None:
            return "..." if field == "full_name" else ""
        return str(getattr(recipient, field, "") or "")

    return RECIPIENT_TOKEN.sub(replace, value)


# Historical document schema. Kept so already saved campaigns can still render.
CHILDREN = {
    "head": ("mj-title", "mj-preview", "mj-font", "mj-breakpoint", "mj-style", "mj-attributes"),
    "mj-attributes": ("mj-all", "mj-body", "mj-section", "mj-wrapper", "mj-column", "mj-text", "mj-image", "mj-button", "mj-divider", "mj-spacer"),
    "body": ("mj-section", "mj-wrapper", "mj-hero", "product", "order-form"),
    "mj-wrapper": ("mj-section", "product", "order-form"),
    "mj-section": ("mj-column", "mj-group"),
    "mj-group": ("mj-column",),
    "mj-column": ("mj-text", "mj-image", "mj-button", "mj-divider", "mj-spacer", "mj-social", "mj-navbar"),
    "mj-hero": ("mj-text", "mj-image", "mj-button", "mj-divider", "mj-spacer"),
    "mj-social": ("mj-social-element",),
    "mj-navbar": ("mj-navbar-link",),
}

COMMON_ATTRS = ("padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "css-class")
ATTRS = {
    "mj-title": (), "mj-preview": (),
    "mj-font": ("name", "href"),
    "mj-breakpoint": ("width",),
    "mj-style": ("inline",),
    "mj-attributes": (),
    "mj-all": ("font-family", "color", "font-size", "line-height", "background-color", "padding"),
    "mj-body": ("background-color", "width", "font-family", "color"),
    "mj-wrapper": COMMON_ATTRS + ("background-color", "background-url", "border", "border-radius"),
    "mj-section": COMMON_ATTRS + ("background-color", "background-url", "direction", "full-width", "border", "border-radius", "text-align"),
    "mj-group": COMMON_ATTRS + ("width", "vertical-align"),
    "mj-column": COMMON_ATTRS + ("width", "background-color", "vertical-align", "border", "border-radius"),
    "mj-hero": COMMON_ATTRS + ("background-color", "background-url", "background-width", "background-height", "mode", "height"),
    "mj-text": COMMON_ATTRS + ("align", "color", "font-family", "font-size", "font-style", "font-weight", "line-height", "letter-spacing", "text-decoration"),
    "mj-image": COMMON_ATTRS + ("src", "href", "alt", "width", "height", "align", "border-radius", "fluid-on-mobile"),
    "mj-button": COMMON_ATTRS + ("href", "align", "background-color", "color", "font-size", "font-weight", "inner-padding", "border-radius", "width", "target"),
    "mj-divider": COMMON_ATTRS + ("border-color", "border-style", "border-width", "width"),
    "mj-spacer": COMMON_ATTRS + ("height",),
    "mj-social": COMMON_ATTRS + ("mode", "align", "icon-size", "font-size"),
    "mj-social-element": ("name", "href", "src", "alt", "background-color", "color", "icon-size"),
    "mj-navbar": COMMON_ATTRS + ("base-url", "hamburger", "ico-color", "align"),
    "mj-navbar-link": ("href", "color", "font-size", "font-weight", "padding", "target"),
    "product": ("campaign-product-id", "title", "media-url"),
    "order-form": (),
}
TEXT_TAGS = {"mj-title", "mj-preview", "mj-style", "mj-text", "mj-button", "mj-social-element", "mj-navbar-link", "product"}
VOID_TAGS = {"mj-font", "mj-breakpoint", "mj-all"}
URL_ATTRS = {"href", "src", "background-url", "base-url", "media-url"}


def _url_is_safe(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "mailto", "tel"} and bool(parsed.netloc or parsed.path)


def validate_document(document):
    if not isinstance(document, dict) or not isinstance(document.get("head"), list) or not isinstance(document.get("body"), list):
        raise ValueError("Das MJML-Dokument benötigt Head und Body.")
    seen = set()
    count = 0

    def validate_nodes(nodes, parent, depth):
        nonlocal count
        if depth > 9 or len(nodes) > 100:
            raise ValueError("Das MJML-Dokument ist zu groß oder zu tief verschachtelt.")
        result = []
        for raw in nodes:
            if not isinstance(raw, dict) or raw.get("type") not in CHILDREN.get(parent, ()):
                raise ValueError(f"Ungültiger MJML-Baustein in {parent}.")
            tag = raw["type"]
            try:
                identifier = str(UUID(str(raw.get("id", ""))))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("Ein MJML-Baustein hat keine gültige Kennung.") from None
            if identifier in seen:
                raise ValueError("MJML-Bausteine müssen eindeutige Kennungen haben.")
            seen.add(identifier)
            count += 1
            if count > 250:
                raise ValueError("Maximal 250 MJML-Bausteine sind möglich.")
            attrs = raw.get("attrs") or {}
            if not isinstance(attrs, dict) or len(attrs) > 30:
                raise ValueError("Ungültige MJML-Eigenschaften.")
            clean_attrs = {}
            for key, value in attrs.items():
                if key not in ATTRS[tag] or not isinstance(value, str) or len(value) > 500:
                    raise ValueError(f"Ungültige Eigenschaft für {tag}: {key}.")
                value = value.strip()
                if value and key in URL_ATTRS and not _url_is_safe(value):
                    raise ValueError(f"Bitte eine gültige URL für {key} eingeben.")
                if value and key in {"src", "background-url", "media-url"} and urlparse(value).scheme not in {"http", "https"}:
                    raise ValueError(f"{key} benötigt eine http- oder https-URL.")
                if key == "campaign-product-id" and (not value.isdecimal() or int(value) <= 0):
                    raise ValueError("Ungültige Produktkennung.")
                if value:
                    clean_attrs[key] = value
            if tag == "product" and "campaign-product-id" not in clean_attrs:
                raise ValueError("Ein Produkt benötigt eine Produktkennung.")
            content = raw.get("content", "")
            if not isinstance(content, str) or len(content) > 10000:
                raise ValueError("Ein Text ist zu lang.")
            children = raw.get("children") or []
            if not isinstance(children, list) or (children and tag not in CHILDREN):
                raise ValueError(f"{tag} kann keine weiteren Bausteine enthalten.")
            if tag not in TEXT_TAGS and content:
                raise ValueError(f"{tag} kann keinen Text enthalten.")
            if tag == "mj-style" and ("<" in content or ">" in content):
                raise ValueError("CSS darf keine HTML-Tags enthalten.")
            result.append({"id": identifier, "type": tag, "attrs": clean_attrs, "content": content, "children": validate_nodes(children, tag, depth + 1)})
        return result

    return {"head": validate_nodes(document["head"], "head", 0), "body": validate_nodes(document["body"], "body", 0)}


def product_ids(document):
    def collect(nodes):
        for node in nodes:
            if node["type"] == "product":
                yield int(node["attrs"]["campaign-product-id"])
            yield from collect(node["children"])
    return set(collect(document["body"]))


def render_visual_mjml(document, *, campaign=None, recipient=None):
    document = validate_document(document)
    offers = {}
    if product_ids(document):
        if campaign is None:
            raise ValueError("Produkte benötigen eine Kampagne.")
        from emails.mjml import _campaign_sales_channel_ids
        from emails.simple_editor import content_for, offer_for_product

        ids = product_ids(document)
        items = campaign.campaign_products.select_related("product").filter(pk__in=ids)
        content = content_for(campaign)
        sales_channel_ids = _campaign_sales_channel_ids(campaign)
        offers = {
            item.pk: offer_for_product(item, content, sales_channel_ids)
            for item in items
        }
        if set(offers) != ids:
            raise ValueError("Ein Produkt gehört nicht zu dieser Kampagne.")

    def render_node(node, parent=""):
        tag = node["type"]
        if tag == "product":
            offer = dict(offers[int(node["attrs"]["campaign-product-id"])])
            if node["attrs"].get("title"):
                offer["title"] = merge_recipient_text(node["attrs"]["title"], recipient)
            if node["attrs"].get("media-url"):
                offer["images"] = [node["attrs"]["media-url"]]
            if node["content"]:
                offer["description"] = merge_recipient_text(node["content"], recipient)
            return render_to_string("emails/_visual_product.mjml", {"offer": offer})
        if tag == "order-form":
            ordered_offers = [offers[pk] for pk in product_order(document) if pk in offers]
            return render_to_string("emails/_visual_order_form.mjml", {"offers": ordered_offers}) if ordered_offers else ""
        attrs = "".join(f' {key}="{escape(value, quote=True)}"' for key, value in node["attrs"].items())
        if tag in VOID_TAGS or parent == "mj-attributes":
            return f"<{tag}{attrs} />"
        if tag == "mj-style":
            body = node["content"]
        elif tag in TEXT_TAGS:
            body = escape(merge_recipient_text(node["content"], recipient)).replace("\n", "<br />")
        else:
            body = "\n".join(render_node(child, tag) for child in node["children"])
        return f"<{tag}{attrs}>{body}</{tag}>"

    head = "\n".join(render_node(node) for node in document["head"])
    body = "\n".join(render_node(node) for node in document["body"])
    return f"<mjml>\n<mj-head>\n{head}\n</mj-head>\n<mj-body>\n{body}\n</mj-body>\n</mjml>"


def product_order(document):
    def collect(nodes):
        for node in nodes:
            if node["type"] == "product":
                yield int(node["attrs"]["campaign-product-id"])
            yield from collect(node["children"])
    return list(dict.fromkeys(collect(document["body"])))
