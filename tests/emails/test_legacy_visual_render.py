"""Existing visual campaigns keep rendering while their editor is retired."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, override_settings
from django.urls import reverse

from emails.admin import EmailCampaignAdmin
from emails.mjml import render_campaign_mjml
from emails.models import EmailCampaign
from emails.visual_editor import render_visual_mjml, validate_document


def node(tag, *, attrs=None, content="", children=None):
    return {
        "id": str(uuid4()), "type": tag, "attrs": attrs or {},
        "content": content, "children": children or [],
    }


def test_legacy_document_validation_and_escaping():
    with pytest.raises(ValueError, match="Ungültiger MJML-Baustein"):
        validate_document({"head": [node("mj-text")], "body": []})

    document = {"head": [], "body": [node("mj-section", children=[node("mj-column", children=[
        node("mj-text", attrs={"color": 'red" onmouseover="alert(1)'}, content="<script>alert(1)</script>"),
    ])])]}
    mjml = render_visual_mjml(document)
    assert "<script>" not in mjml
    assert "&lt;script&gt;" in mjml
    assert 'color="red&quot; onmouseover=&quot;alert(1)"' in mjml

    document["body"][0]["children"][0]["children"][0]["attrs"] = {"href": "javascript:alert(1)"}
    with pytest.raises(ValueError, match="Ungültige Eigenschaft"):
        validate_document(document)


def test_legacy_recipient_text_is_merged():
    document = {"head": [], "body": [node("mj-section", children=[node("mj-column", children=[
        node("mj-text", content="Hallo {{ recipient.full_name }},"),
    ])])]}
    assert "Hallo ...," in render_visual_mjml(document)
    sent = render_visual_mjml(document, recipient=SimpleNamespace(full_name="<Frau Test>"))
    assert "Hallo &lt;Frau Test&gt;," in sent


def test_saved_visual_product_still_renders():
    document = {"head": [], "body": [node("product", attrs={"campaign-product-id": "9"})]}
    rows = Mock()
    rows.select_related.return_value.filter.return_value = [SimpleNamespace(pk=9)]
    campaign = SimpleNamespace(layout_mode="visual", editor_content={"visual_document": document}, campaign_products=rows)
    offer = {
        "id": 9, "section_heading": "", "title": "Mappe", "description": "Fürs Büro", "url": "https://example.com",
        "images": [], "list_price": "100,00", "current_price": "90,00", "has_special": True,
        "discount_pct": 10, "unit": "St.",
    }
    with patch("emails.mjml._campaign_sales_channel_ids", return_value=()), patch(
        "emails.simple_editor.offer_for_product", return_value=offer,
    ):
        mjml = render_campaign_mjml(campaign)
    assert "Mappe" in mjml
    assert "90,00 €" in mjml
    assert "visual-product-9" in mjml


def test_visual_campaign_without_document_uses_simple_template():
    campaign = SimpleNamespace(layout_mode="visual", editor_content={"headline": "Neue Aktion"})
    with patch("emails.simple_editor.build_simple_mjml", return_value="<mjml>einfach</mjml>") as renderer:
        assert render_campaign_mjml(campaign) == "<mjml>einfach</mjml>"
    renderer.assert_called_once_with(campaign, recipient=None)


def test_retired_editor_url_redirects_to_simple_editor():
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    request = RequestFactory().get("/admin/emails/emailcampaign/8/visual-editor/")
    with patch.object(admin, "_editor_campaign") as access_check:
        response = admin.retired_visual_editor_view(request, 8)
    access_check.assert_called_once_with(request, 8)
    assert response.status_code == 302
    assert response["Location"] == reverse("admin:emails_emailcampaign_simple_editor", args=[8])


def test_legacy_campaign_opens_in_simple_editor():
    rows = Mock()
    rows.select_related.return_value.order_by.return_value = []
    campaign = SimpleNamespace(
        pk=8, internal_title="Aktion", layout_mode="visual",
        editor_content={"visual_document": {"head": [], "body": []}}, campaign_products=rows,
    )
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    request = RequestFactory().get("/admin/emails/emailcampaign/8/editor/")
    with patch.object(admin, "_editor_campaign", return_value=campaign), override_settings(
        STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
    ):
        response = admin.simple_editor_view(request, 8)
    assert response.status_code == 200
    assert b"Einfacher E-Mail-Editor" in response.content
    assert b"gespeicherten visuellen Aufbau" in response.content
    assert b"visual_editor.js" not in response.content
    assert b"visual_document" not in response.content


def test_first_simple_save_converts_legacy_campaign_and_preserves_original_document():
    original = {"head": [], "body": []}
    campaign = SimpleNamespace(
        layout_mode="visual", editor_content={"visual_document": original}, save=Mock(),
    )
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    request = RequestFactory().post(
        "/admin/emails/emailcampaign/8/editor/save/",
        data=json.dumps({"headline": "Neue Aktion"}), content_type="application/json",
    )
    with patch.object(admin, "_editor_campaign", return_value=campaign):
        response = admin.simple_editor_save_view(request, 8)
    assert response.status_code == 200
    assert campaign.layout_mode == EmailCampaign.LayoutMode.SIMPLE
    assert campaign.editor_content["headline"] == "Neue Aktion"
    assert campaign.editor_content["visual_document"] == original
    campaign.save.assert_called_once_with(update_fields=["editor_content", "layout_mode"])
