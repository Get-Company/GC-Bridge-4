from __future__ import annotations
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods

from emails.models import MjmlComponent
from emails_v2.catalog import MJML_TAGS
from emails_v2.models import EmailBuilderCampaign, EmailBlock
from emails_v2.mjml import render_campaign_preview
from emails_v2.variable_parser import infer_field_type


def _child_map(campaign: EmailBuilderCampaign) -> dict:
    blocks = list(campaign.blocks.select_related("component").all())
    result: dict = {}
    for b in blocks:
        result.setdefault(b.parent_id, []).append(b)
    return result


@staff_member_required
def campaign_list(request):
    campaigns = EmailBuilderCampaign.objects.all()
    return render(request, "email_builder/campaign_list.html", {"campaigns": campaigns})


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
    return render(request, "email_builder/editor.html", {
        "campaign": campaign,
        "mjml_tags": MJML_TAGS,
        "custom_components": MjmlComponent.objects.order_by("name"),
        "top_blocks": sorted((_child_map(campaign)).get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": _child_map(campaign),
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_create(request):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=request.POST.get("campaign_id"))
    parent_id = request.POST.get("parent_id") or None
    component_id = request.POST.get("component_id") or None
    tag = request.POST.get("tag", "mj-section")

    last_order = EmailBlock.objects.filter(campaign=campaign, parent_id=parent_id).count()
    EmailBlock.objects.create(
        campaign=campaign, tag=tag, parent_id=parent_id,
        component_id=component_id, order=last_order,
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
    block.save(update_fields=["order"])
    return HttpResponse(status=204)


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
