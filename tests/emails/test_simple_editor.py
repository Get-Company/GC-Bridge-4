from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from emails.mjml import ProductEmailProxy
from emails.simple_editor import build_simple_mjml


class ProductRows:
    def __init__(self, rows):
        self.rows = rows

    def select_related(self, *args):
        return self

    def order_by(self, *args):
        return self.rows


class FakeProduct:
    pk = 17
    erp_nr = "224453"
    name = "Blättersicht-Mappe"
    description_short = "<p>Transparent & praktisch</p>"
    factor = 100
    unit = "St."
    min_purchase = 20
    purchase_unit = 10

    def get_images(self):
        return [SimpleNamespace(url="https://assets.classei.de/img/224453.jpg")]


def test_simple_newsletter_uses_fixed_frame_and_editable_fields():
    item = SimpleNamespace(
        pk=9, product=FakeProduct(),
        special_price_override=Decimal("99.95"), discount_pct=None,
    )
    campaign = SimpleNamespace(
        editor_content={"headline": "Neue Aktion", "product_texts": {
            "17": {"section_heading": "Mappen", "media_urls": "https://assets.classei.de/img/neu.jpg"}
        }},
        campaign_products=ProductRows([item]),
    )
    with patch("emails.simple_editor._campaign_sales_channel_ids", return_value=()), patch.object(
        ProductEmailProxy, "_get_price_entry", return_value=SimpleNamespace(
            get_standard_price=lambda **kwargs: Decimal("114.05"),
            get_special_price=lambda **kwargs: None,
        ),
    ):
        mjml = build_simple_mjml(campaign)

    assert "Neue Aktion" in mjml
    assert "Mappen" in mjml
    assert "99,95 €" in mjml
    assert "https://assets.classei.de/img/neu.jpg" in mjml
    assert "224453.jpg" not in mjml
    assert "https://www.classei-shop.com/search?sSearch=224453" in mjml
    assert "{modify}hier{/modify}" in mjml


def test_editor_text_is_escaped_in_mjml():
    campaign = SimpleNamespace(
        editor_content={"headline": "<script>alert(1)</script>"},
        campaign_products=ProductRows([]),
    )
    with patch("emails.simple_editor._campaign_sales_channel_ids", return_value=()):
        mjml = build_simple_mjml(campaign)
    assert "<script>" not in mjml
    assert "&lt;script&gt;" in mjml


def test_percentage_override_takes_precedence_over_catalog_special_price():
    product = FakeProduct()
    proxy = ProductEmailProxy(product, discount_pct=Decimal("15"))
    with patch.object(ProductEmailProxy, "_get_price_entry", return_value=SimpleNamespace(
        get_standard_price=lambda **kwargs: Decimal("100.00"),
        get_special_price=lambda **kwargs: Decimal("90.00"),
    )):
        assert proxy.email_special_price == Decimal("85.00")


def test_editor_save_only_accepts_campaign_product_texts():
    import json
    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory
    from emails.admin import EmailCampaignAdmin
    from emails.models import EmailCampaign
    from unittest.mock import Mock

    campaign = SimpleNamespace(editor_content={}, campaign_products=Mock())
    campaign.campaign_products.values_list.return_value = [17]
    campaign.save = Mock()
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    payload = {
        "headline": "Neue Überschrift",
        "product_texts": {
            "17": {"section_heading": "Mappen", "media_urls": "https://assets.classei.de/img/a.jpg"},
            "99": {"title": "Fremdprodukt"},
        },
    }
    request = RequestFactory().post("/editor/save/", data=json.dumps(payload), content_type="application/json")
    with patch.object(admin, "_editor_campaign", return_value=campaign):
        response = admin.simple_editor_save_view(request, 1)
    assert response.status_code == 200
    assert campaign.editor_content["headline"] == "Neue Überschrift"
    assert list(campaign.editor_content["product_texts"]) == ["17"]
    campaign.save.assert_called_once_with(update_fields=["editor_content"])


def test_editor_rejects_unsafe_media_url():
    import json
    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory
    from emails.admin import EmailCampaignAdmin
    from emails.models import EmailCampaign
    from unittest.mock import Mock

    campaign = SimpleNamespace(editor_content={}, campaign_products=Mock(), save=Mock())
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    request = RequestFactory().post(
        "/editor/save/", data=json.dumps({"logo_url": "javascript:alert(1)"}),
        content_type="application/json",
    )
    with patch.object(admin, "_editor_campaign", return_value=campaign):
        response = admin.simple_editor_save_view(request, 1)
    assert response.status_code == 400
    campaign.save.assert_not_called()


def test_interstitial_heading_renders_between_selected_products():
    first = SimpleNamespace(
        pk=9, product=FakeProduct(), special_price_override=None, discount_pct=None,
    )
    second_product = FakeProduct()
    second_product.pk = 18
    second_product.erp_nr = "900001"
    second_product.name = "Business-Set"
    second = SimpleNamespace(
        pk=10, product=second_product, special_price_override=None, discount_pct=None,
    )
    heading_id = "e8af9f3b-52cf-4568-91c8-48031c5bec10"
    campaign = SimpleNamespace(
        editor_content={"headings": [{
            "id": heading_id, "after_product_id": "9", "title": "Zwischenüberschrift",
            "center_text": "Einfach antworten", "right_text": "Telefon:\n12345",
        }]},
        campaign_products=ProductRows([first, second]),
    )
    with patch("emails.simple_editor._campaign_sales_channel_ids", return_value=()), patch.object(
        ProductEmailProxy, "_get_price_entry", return_value=None,
    ):
        mjml = build_simple_mjml(campaign)
    assert mjml.index("editor-product-9") < mjml.index(f"editor-heading-{heading_id}")
    assert mjml.index(f"editor-heading-{heading_id}") < mjml.index("editor-product-10")
    assert "Einfach antworten" in mjml
    assert "Telefon:<br>12345" in mjml


def test_interstitial_heading_is_escaped():
    heading_id = "68ef82fd-35bd-4188-a056-c7df61d3cf11"
    campaign = SimpleNamespace(
        editor_content={"headings": [{
            "id": heading_id, "after_product_id": "", "title": "<script>alert(1)</script>",
            "center_text": "", "right_text": "",
        }]},
        campaign_products=ProductRows([]),
    )
    with patch("emails.simple_editor._campaign_sales_channel_ids", return_value=()):
        mjml = build_simple_mjml(campaign)
    assert "<script>" not in mjml
    assert "&lt;script&gt;" in mjml


def test_editor_saves_interstitial_heading_position():
    import json
    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory
    from emails.admin import EmailCampaignAdmin
    from emails.models import EmailCampaign
    from unittest.mock import Mock

    heading_id = "d9fd94d1-648f-412a-b00a-4fbdf190299d"
    campaign = SimpleNamespace(editor_content={}, campaign_products=Mock(), save=Mock())
    campaign.campaign_products.values_list.return_value = [9]
    admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
    request = RequestFactory().post("/editor/save/", data=json.dumps({"headings": [{
        "id": heading_id, "after_product_id": "9", "title": "Bestellformular",
        "center_text": "Einfach antworten", "right_text": "Telefon",
    }]}), content_type="application/json")
    with patch.object(admin, "_editor_campaign", return_value=campaign):
        response = admin.simple_editor_save_view(request, 1)
    assert response.status_code == 200
    assert campaign.editor_content["headings"][0]["after_product_id"] == "9"
    assert campaign.editor_content["headings"][0]["title"] == "Bestellformular"
