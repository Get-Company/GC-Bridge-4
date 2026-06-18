from __future__ import annotations
import jinja2
from urllib.parse import quote_plus

from emails.mjml import ProductEmailProxy, compile_mjml_to_html  # reuse existing CLI wrapper
from emails_v2.models import EmailBuilderCampaign, EmailBlock

_jinja_env = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)
_jinja_env.filters["urlencode"] = lambda value: quote_plus(str(value or ""))
_jinja_env.filters["format_price"] = lambda value, decimals=2: "" if value is None else f"{value:.{decimals}f}"


def _render_value(value: object, context: dict) -> str:
    try:
        return _jinja_env.from_string(str(value)).render(context)
    except Exception:
        return str(value)


def _attrs_str(attributes: dict, context: dict) -> str:
    if not attributes:
        return ""
    return " " + " ".join(f'{k}="{_render_value(v, context)}"' for k, v in attributes.items())


def _block_context(block: EmailBlock, context: dict, product_map: dict[int, ProductEmailProxy]) -> dict:
    block_context = {**context, **(block.variables or {})}
    if block.campaign_product_id and block.campaign_product_id in product_map:
        block_context["product"] = product_map[block.campaign_product_id]
    return block_context


def _render_block(
    block: EmailBlock,
    child_map: dict[int | None, list[EmailBlock]],
    context: dict,
    product_map: dict[int, ProductEmailProxy],
) -> str:
    block_context = _block_context(block, context, product_map)
    if block.component_id and block.component:
        markup = block.component.mjml_markup
        try:
            return _jinja_env.from_string(markup).render(block_context)
        except Exception:
            return ""

    children = sorted(child_map.get(block.id, []), key=lambda b: (b.order, b.id))
    inner = _render_value(block.variables.get("content", ""), block_context)
    for child in children:
        inner += _render_block(child, child_map, block_context, product_map)

    attrs = _attrs_str(block.attributes, block_context)
    return f"<{block.tag}{attrs}>{inner}</{block.tag}>"


def build_mjml_from_blocks(campaign: EmailBuilderCampaign) -> str:
    campaign_products = list(
        campaign.campaign_products.select_related("product").order_by("order", "id")
    )
    product_map = {
        campaign_product.id: ProductEmailProxy(
            campaign_product.product,
            special_price_override=campaign_product.special_price_override,
            discount_pct=campaign_product.discount_pct,
        )
        for campaign_product in campaign_products
    }
    context = {"products": list(product_map.values())}

    blocks = list(campaign.blocks.select_related("component", "campaign_product__product").all())

    child_map: dict[int | None, list[EmailBlock]] = {}
    for block in blocks:
        child_map.setdefault(block.parent_id, []).append(block)

    top_blocks = sorted(child_map.get(None, []), key=lambda b: (b.order, b.id))
    body_inner = "".join(_render_block(b, child_map, context, product_map) for b in top_blocks)

    css_block = f"<mj-style>{campaign.global_css}</mj-style>" if campaign.global_css.strip() else ""
    return f"<mjml><mj-head>{css_block}</mj-head><mj-body>{body_inner}</mj-body></mjml>"


def render_campaign_preview(campaign: EmailBuilderCampaign) -> str:
    return compile_mjml_to_html(build_mjml_from_blocks(campaign))
