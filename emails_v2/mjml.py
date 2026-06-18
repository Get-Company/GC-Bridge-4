from __future__ import annotations
import jinja2
from emails.mjml import compile_mjml_to_html  # reuse existing CLI wrapper
from emails_v2.models import EmailBuilderCampaign, EmailBlock

_jinja_env = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)


def _attrs_str(attributes: dict) -> str:
    if not attributes:
        return ""
    return " " + " ".join(f'{k}="{v}"' for k, v in attributes.items())


def _render_block(block: EmailBlock, child_map: dict[int | None, list[EmailBlock]]) -> str:
    if block.component_id and block.component:
        markup = block.component.mjml_markup
        try:
            return _jinja_env.from_string(markup).render(block.variables)
        except Exception:
            return ""

    children = sorted(child_map.get(block.id, []), key=lambda b: (b.order, b.id))
    inner = block.variables.get("content", "")
    for child in children:
        inner += _render_block(child, child_map)

    attrs = _attrs_str(block.attributes)
    return f"<{block.tag}{attrs}>{inner}</{block.tag}>"


def build_mjml_from_blocks(campaign: EmailBuilderCampaign) -> str:
    blocks = list(campaign.blocks.select_related("component").all())

    child_map: dict[int | None, list[EmailBlock]] = {}
    for block in blocks:
        child_map.setdefault(block.parent_id, []).append(block)

    top_blocks = sorted(child_map.get(None, []), key=lambda b: (b.order, b.id))
    body_inner = "".join(_render_block(b, child_map) for b in top_blocks)

    css_block = f"<mj-style>{campaign.global_css}</mj-style>" if campaign.global_css.strip() else ""
    return f"<mjml><mj-head>{css_block}</mj-head><mj-body>{body_inner}</mj-body></mjml>"


def render_campaign_preview(campaign: EmailBuilderCampaign) -> str:
    return compile_mjml_to_html(build_mjml_from_blocks(campaign))
