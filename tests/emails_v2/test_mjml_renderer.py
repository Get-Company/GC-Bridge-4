import pytest
from decimal import Decimal
from datetime import datetime

from django.utils import timezone

from emails_v2.models import EmailBuilderCampaign, EmailBlock, EmailBuilderCampaignProduct
from emails_v2.mjml import build_mjml_from_blocks


@pytest.mark.django_db
def test_empty_campaign_produces_valid_mjml():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Empty")
    result = build_mjml_from_blocks(campaign)
    assert "<mjml>" in result
    assert "<mj-body>" in result
    assert "</mj-body>" in result


@pytest.mark.django_db
def test_section_rendered():
    campaign = EmailBuilderCampaign.objects.create(internal_title="S")
    EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    result = build_mjml_from_blocks(campaign)
    assert "<mj-section>" in result
    assert "</mj-section>" in result


@pytest.mark.django_db
def test_section_with_column_and_text():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Nested")
    section = EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign, tag="mj-text", parent=col, order=0,
        variables={"content": "Hello World"}
    )
    result = build_mjml_from_blocks(campaign)
    assert "<mj-text>" in result
    assert "Hello World" in result


@pytest.mark.django_db
def test_attributes_rendered():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Attrs")
    EmailBlock.objects.create(
        campaign=campaign, tag="mj-section", order=0,
        attributes={"padding": "20px", "background-color": "#fff"}
    )
    result = build_mjml_from_blocks(campaign)
    assert 'padding="20px"' in result
    assert 'background-color="#fff"' in result


@pytest.mark.django_db
def test_empty_attributes_are_not_rendered():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Attrs")
    EmailBlock.objects.create(
        campaign=campaign,
        tag="mj-image",
        order=0,
        attributes={"src": "", "alt": "", "width": "100px"},
    )
    result = build_mjml_from_blocks(campaign)
    assert 'src=""' not in result
    assert 'alt=""' not in result
    assert 'width="100px"' in result


@pytest.mark.django_db
def test_custom_component_rendered_via_jinja(db):
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(
        name="Greet", mjml_markup="<mj-text>{{ greeting }}</mj-text>"
    )
    campaign = EmailBuilderCampaign.objects.create(internal_title="Custom")
    section = EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign, tag="mj-section", parent=col, order=0,
        component=comp, variables={"greeting": "Hallo!"}
    )
    result = build_mjml_from_blocks(campaign)
    assert "Hallo!" in result


@pytest.mark.django_db
def test_ordering_respected():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Order")
    EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=1, attributes={"css-class": "second"})
    EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0, attributes={"css-class": "first"})
    result = build_mjml_from_blocks(campaign)
    assert result.index('css-class="first"') < result.index('css-class="second"')


@pytest.mark.django_db
def test_section_product_context_inherited_by_child_blocks():
    from products.models import Product

    campaign = EmailBuilderCampaign.objects.create(internal_title="Products")
    product = Product.objects.create(erp_nr="710001", name="Testprodukt")
    campaign_product = EmailBuilderCampaignProduct.objects.create(
        campaign=campaign,
        product=product,
        order=0,
    )
    section = EmailBlock.objects.create(
        campaign=campaign,
        tag="mj-section",
        order=0,
        campaign_product=campaign_product,
    )
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign,
        tag="mj-text",
        parent=col,
        variables={"content": "{{ product.name }} / {{ products[0].erp_nr }}"},
        order=0,
    )

    result = build_mjml_from_blocks(campaign)

    assert "Testprodukt / 710001" in result


@pytest.mark.django_db
def test_offer_valid_until_text_uses_latest_related_product_special_end_date():
    from products.models import Price, Product

    campaign = EmailBuilderCampaign.objects.create(internal_title="Products")
    product_a = Product.objects.create(erp_nr="710001", name="Testprodukt A")
    product_b = Product.objects.create(erp_nr="710002", name="Testprodukt B")
    Price.objects.create(
        product=product_a,
        price=Decimal("10.00"),
        special_price=Decimal("8.00"),
        special_end_date=timezone.make_aware(datetime(2026, 7, 15)),
    )
    Price.objects.create(
        product=product_b,
        price=Decimal("20.00"),
        special_price=Decimal("16.00"),
        special_end_date=timezone.make_aware(datetime(2026, 7, 31)),
    )
    campaign_product_a = EmailBuilderCampaignProduct.objects.create(
        campaign=campaign,
        product=product_a,
        order=0,
    )
    EmailBuilderCampaignProduct.objects.create(
        campaign=campaign,
        product=product_b,
        order=1,
    )
    section = EmailBlock.objects.create(
        campaign=campaign,
        tag="mj-section",
        order=0,
        campaign_product=campaign_product_a,
    )
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign,
        tag="mj-text",
        parent=col,
        variables={
            "content": (
                "{% if special_price and offer_valid_until_text %}"
                "{{ offer_valid_until_text }} / {{ special_end_date|format_date }}"
                "{% endif %}"
            )
        },
        order=0,
    )

    result = build_mjml_from_blocks(campaign)

    assert "Angebot gültig bis 31.07.2026" in result
    assert "31.07.2026" in result
    assert "15.07.2026" not in result


@pytest.mark.django_db
def test_product_context_on_non_section_block_is_ignored():
    from products.models import Product

    campaign = EmailBuilderCampaign.objects.create(internal_title="Products")
    product = Product.objects.create(erp_nr="710001", name="Testprodukt")
    campaign_product = EmailBuilderCampaignProduct.objects.create(
        campaign=campaign,
        product=product,
        order=0,
    )
    section = EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign,
        tag="mj-text",
        parent=col,
        campaign_product=campaign_product,
        variables={"content": "{{ product.name|default('NO_PRODUCT') }}"},
        order=0,
    )

    result = build_mjml_from_blocks(campaign)

    assert "NO_PRODUCT" in result
    assert "Testprodukt" not in result
