import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from emails.admin import EmailCampaignAdmin
from emails.models import EmailCampaign
from emails.visual_editor import default_document, new_node, remap_product_ids, render_visual_mjml, validate_document


def test_default_document_has_head_body_and_preserves_product_order():
    heading = {"id": "710152a2-d18f-4dbe-8cb0-d84d99d52840", "after_product_id": "9", "title": "Bestellformular", "center_text": "Antworten", "right_text": "Anrufen"}
    document = default_document({"headline": "Neue Aktion", "headings": [heading]}, [9, 10])
    validated = validate_document(document)
    mjml = render_visual_mjml({**validated, "body": [node for node in validated["body"] if node["type"] != "product"]})

    assert validated["head"][0]["type"] == "mj-title"
    assert [node["attrs"]["campaign-product-id"] for node in validated["body"] if node["type"] == "product"] == ["9", "10"]
    assert mjml.index("Neue Aktion") < mjml.index("Bestellformular")
    assert "Antworten" in mjml


def test_document_rejects_invalid_nesting_and_unsafe_url():
    with pytest.raises(ValueError, match="Ungültiger MJML-Baustein"):
        validate_document({"head": [new_node("mj-text", content="wrong")], "body": []})
    document = default_document()
    document["body"][1]["children"][0]["children"][0]["attrs"]["src"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="gültige URL"):
        validate_document(document)


def test_editor_escapes_text_and_attributes():
    document = {"head": [], "body": [new_node("mj-section", children=[new_node("mj-column", children=[
        new_node("mj-text", attrs={"color": "red\" onmouseover=\"alert(1)"}, content="<script>alert(1)</script>")
    ])])]}
    mjml = render_visual_mjml(document)

    assert "<script>" not in mjml
    assert "&lt;script&gt;" in mjml
    assert 'color="red&quot; onmouseover=&quot;alert(1)"' in mjml


def test_preview_marks_visible_nodes_without_changing_saved_mjml():
    document = default_document()
    normal = render_visual_mjml(document)
    preview = render_visual_mjml(document, editor_classes=True)
    node_id = document["body"][1]["id"]
    assert f"visual-node-{node_id}" not in normal
    assert f"visual-node-{node_id}" in preview


def test_recipient_name_is_merged_and_escaped_for_send():
    document = default_document()
    intro = next(node for section in document["body"] for column in section["children"] if section["type"] == "mj-section" for node in column["children"] if node["type"] == "mj-text" and "recipient.full_name" in node["content"])
    assert "{{ recipient.full_name }}" in intro["content"]
    preview = render_visual_mjml(document)
    sent = render_visual_mjml(document, recipient=SimpleNamespace(full_name="<Frau Test>"))
    assert "Hallo ...," in preview
    assert "Hallo &lt;Frau Test&gt;," in sent
    assert "<Frau Test>" not in sent


def test_visual_save_switches_layout_and_rejects_foreign_product():
    campaign = SimpleNamespace(editor_content={"headline": "Alt"}, layout_mode="simple", save=Mock(), campaign_products=Mock())
    campaign.campaign_products.values_list.return_value = [9]
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    document = default_document(product_ids=[9])
    request = RequestFactory().post("/visual-editor/save/", data=json.dumps(document), content_type="application/json")
    with patch.object(admin, "_visual_campaign", return_value=campaign), patch("emails.visual_editor.render_visual_mjml", return_value="<mjml />"), patch("emails.admin.compile_mjml_to_html", return_value="<html></html>"):
        response = admin.visual_editor_save_view(request, 1)
    assert response.status_code == 200
    assert campaign.layout_mode == EmailCampaign.LayoutMode.VISUAL
    assert campaign.editor_content["headline"] == "Alt"
    campaign.save.assert_called_once_with(update_fields=["editor_content", "layout_mode"])

    campaign.save.reset_mock()
    foreign = default_document(product_ids=[10])
    request = RequestFactory().post("/visual-editor/save/", data=json.dumps(foreign), content_type="application/json")
    with patch.object(admin, "_visual_campaign", return_value=campaign):
        response = admin.visual_editor_save_view(request, 1)
    assert response.status_code == 400
    campaign.save.assert_not_called()


def test_copy_remaps_product_blocks_without_changing_source():
    document = default_document(product_ids=[9, 10])
    copied = remap_product_ids(document, {9: 90, 10: 100})
    source_ids = [node["attrs"]["campaign-product-id"] for node in document["body"] if node["type"] == "product"]
    copied_ids = [node["attrs"]["campaign-product-id"] for node in copied["body"] if node["type"] == "product"]
    assert source_ids == ["9", "10"]
    assert copied_ids == ["90", "100"]


def test_visual_editor_page_renders_without_database():
    from django.test import override_settings

    rows = Mock()
    rows.select_related.return_value.order_by.return_value = []
    campaign = SimpleNamespace(pk=8, internal_title="Aktion", layout_mode="visual", editor_content={}, campaign_products=rows)
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    request = RequestFactory().get("/visual-editor/")
    with patch.object(admin, "_visual_campaign", return_value=campaign), override_settings(
        STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
    ):
        response = admin.visual_editor_view(request, 8)
    assert response.status_code == 200
    assert b"visual-editor" in response.content
    assert b"visual-products" in response.content


def test_campaign_render_uses_visual_product_block():
    from emails.mjml import render_campaign_mjml

    document = {"head": [], "body": [new_node("product", attrs={"campaign-product-id": "9"})]}
    rows = Mock()
    rows.select_related.return_value.filter.return_value = [SimpleNamespace(pk=9)]
    campaign = SimpleNamespace(layout_mode="visual", editor_content={"visual_document": document}, campaign_products=rows)
    offer = {
        "id": 9, "section_heading": "", "title": "Mappe", "description": "Fürs Büro", "url": "https://example.com",
        "images": [], "list_price": "100,00", "current_price": "90,00", "has_special": True,
        "discount_pct": 10, "unit": "St.",
    }
    with patch("emails.mjml._campaign_sales_channel_ids", return_value=()), patch("emails.simple_editor.offer_for_product", return_value=offer):
        mjml = render_campaign_mjml(campaign)
    assert "Mappe" in mjml
    assert "90,00 €" in mjml
    assert "visual-product-9" in mjml
