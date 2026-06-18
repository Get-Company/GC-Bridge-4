from __future__ import annotations
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods

from emails.models import MjmlComponent
from emails_v2.catalog import MJML_TAGS, MJML_TAG_MAP
from emails_v2.models import EmailBuilderCampaign, EmailBlock
from emails_v2.mjml import render_campaign_preview
from emails_v2.variable_parser import infer_field_type


def _child_map(campaign: EmailBuilderCampaign) -> dict:
    blocks = list(campaign.blocks.select_related("component").all())
    result: dict = {}
    for b in blocks:
        result.setdefault(b.parent_id, []).append(b)
    return result


_SECTION_CHILD_TAGS = {"mj-column", "mj-group"}
_LAYOUT_TAGS = {"mj-section", "mj-column", "mj-wrapper", "mj-group", "mj-hero"}


def _default_attributes_for_tag(tag: str) -> dict:
    attrs = dict(MJML_TAG_MAP.get(tag).default_attributes) if tag in MJML_TAG_MAP else {}
    if tag == "mj-image":
        attrs.setdefault("src", "")
        attrs.setdefault("alt", "")
        attrs.setdefault("href", "")
    elif tag == "mj-button":
        attrs.setdefault("href", "")
    return attrs


def _next_order(campaign: EmailBuilderCampaign, parent_id: int | None) -> int:
    return EmailBlock.objects.filter(campaign=campaign, parent_id=parent_id).count()


def _create_block(
    campaign: EmailBuilderCampaign,
    *,
    tag: str,
    parent_id: int | None,
    component_id: str | None,
) -> EmailBlock:
    parent = (
        EmailBlock.objects.filter(campaign=campaign, pk=parent_id).first()
        if parent_id
        else None
    )

    if parent and parent.tag == "mj-wrapper" and tag != "mj-section":
        section = EmailBlock.objects.create(
            campaign=campaign,
            tag="mj-section",
            parent=parent,
            order=_next_order(campaign, parent.id),
            attributes=_default_attributes_for_tag("mj-section"),
        )
        column = EmailBlock.objects.create(
            campaign=campaign,
            tag="mj-column",
            parent=section,
            order=0,
            attributes=_default_attributes_for_tag("mj-column"),
        )
        parent_id = column.id
    elif (
        parent
        and parent.tag == "mj-section"
        and (component_id or tag not in _SECTION_CHILD_TAGS | _LAYOUT_TAGS)
    ):
        column = EmailBlock.objects.create(
            campaign=campaign,
            tag="mj-column",
            parent=parent,
            order=_next_order(campaign, parent.id),
            attributes=_default_attributes_for_tag("mj-column"),
        )
        parent_id = column.id

    return EmailBlock.objects.create(
        campaign=campaign,
        tag=tag,
        parent_id=parent_id,
        component_id=component_id,
        order=_next_order(campaign, parent_id),
        attributes=_default_attributes_for_tag(tag),
    )


@staff_member_required
def campaign_list(request):
    campaigns = EmailBuilderCampaign.objects.all()
    return render(request, "email_builder/campaign_list.html", {"campaigns": campaigns})


@staff_member_required
@require_http_methods(["POST"])
def campaign_delete(request, campaign_id):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    campaign.delete()
    return redirect("email_builder:list")


@staff_member_required
@require_http_methods(["POST"])
def campaign_duplicate(request, campaign_id):
    source = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    new_campaign = EmailBuilderCampaign.objects.create(
        internal_title=f"{source.internal_title} (Kopie)",
        global_css=source.global_css,
    )
    blocks = list(source.blocks.all())
    id_map: dict[int, int] = {}
    for block in sorted(blocks, key=lambda b: (b.parent_id or 0, b.order, b.id)):
        new_block = EmailBlock.objects.create(
            campaign=new_campaign,
            parent_id=id_map.get(block.parent_id) if block.parent_id else None,
            tag=block.tag,
            component_id=block.component_id,
            attributes=dict(block.attributes),
            variables=dict(block.variables),
            order=block.order,
        )
        id_map[block.id] = new_block.id
    return redirect("email_builder:editor", campaign_id=new_campaign.pk)


@staff_member_required
@require_http_methods(["POST"])
def htmx_campaign_css_save(request, campaign_id):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    campaign.global_css = request.POST.get("global_css", "")
    campaign.save(update_fields=["global_css"])
    return HttpResponse(status=204)


@staff_member_required
def campaign_create(request):
    if request.method == "POST":
        title = request.POST.get("internal_title", "Neue Kampagne")
        campaign = EmailBuilderCampaign.objects.create(internal_title=title)
        return redirect("email_builder:editor", campaign_id=campaign.pk)
    return render(request, "email_builder/campaign_create.html")


@staff_member_required
def campaign_editor(request, campaign_id):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    cm = _child_map(campaign)
    return render(request, "email_builder/editor.html", {
        "campaign": campaign,
        "mjml_tags": MJML_TAGS,
        "custom_components": MjmlComponent.objects.order_by("name"),
        "top_blocks": sorted(cm.get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": cm,
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_create(request):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=request.POST.get("campaign_id"))
    parent_id = int(request.POST["parent_id"]) if request.POST.get("parent_id") else None
    component_id = request.POST.get("component_id") or None
    tag = request.POST.get("tag", "mj-section")

    _create_block(
        campaign,
        tag=tag,
        parent_id=parent_id,
        component_id=component_id,
    )
    cm = _child_map(campaign)
    return render(request, "email_builder/_canvas.html", {
        "campaign": campaign,
        "top_blocks": sorted(cm.get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": cm,
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_reorder(request, block_id):
    block = get_object_or_404(EmailBlock, pk=block_id)
    block.order = int(request.POST.get("order", 0))
    new_parent_id = request.POST.get("parent_id") or None
    update_fields = ["order"]
    if new_parent_id != str(block.parent_id or ""):
        block.parent_id = int(new_parent_id) if new_parent_id else None
        update_fields.append("parent")
    block.save(update_fields=update_fields)
    cm = _child_map(block.campaign)
    return render(request, "email_builder/_canvas.html", {
        "campaign": block.campaign,
        "top_blocks": sorted(cm.get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": cm,
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_delete(request, block_id):
    block = get_object_or_404(EmailBlock, pk=block_id)
    campaign = block.campaign
    block.delete()
    cm = _child_map(campaign)
    return render(request, "email_builder/_canvas.html", {
        "campaign": campaign,
        "top_blocks": sorted(cm.get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": cm,
    })


_CONTENT_TAGS = {"mj-text", "mj-button", "mj-raw"}

@staff_member_required
def htmx_variable_panel(request, block_id):
    block = get_object_or_404(EmailBlock.objects.select_related("component"), pk=block_id)
    variable_fields = []
    if block.component_id and block.component:
        for var_name in block.component.detected_variables:
            variable_fields.append({
                "name": var_name,
                "field_type": infer_field_type(var_name),
                "value": block.variables.get(var_name, ""),
                "label": block.component.variable_labels.get(var_name, var_name.replace("_", " ").title()),
            })
    elif block.tag in _CONTENT_TAGS:
        variable_fields.append({
            "name": "content",
            "field_type": "textarea",
            "value": block.variables.get("content", ""),
            "label": "Inhalt",
        })
    return render(request, "email_builder/_variable_panel.html", {
        "block": block,
        "variable_fields": variable_fields,
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_variable_save(request, block_id):
    block = get_object_or_404(EmailBlock.objects.select_related("component"), pk=block_id)
    if block.component_id and block.component:
        for var_name in block.component.detected_variables:
            if var_name in request.POST:
                block.variables[var_name] = request.POST[var_name]
    elif block.tag in _CONTENT_TAGS and "content" in request.POST:
        block.variables["content"] = request.POST["content"]
    for key, value in request.POST.items():
        if key.startswith("attr_"):
            block.attributes[key[5:]] = value
    block.save(update_fields=["variables", "attributes"])
    return HttpResponse(status=204)


@staff_member_required
@require_http_methods(["POST"])
def htmx_preview(request, campaign_id):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    try:
        html = render_campaign_preview(campaign)
    except Exception as e:
        html = f"<html><body><p style='color:red'>Preview-Fehler: {e}</p></body></html>"
    return HttpResponse(html)
