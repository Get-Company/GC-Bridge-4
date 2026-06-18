import pytest
from emails_v2.models import EmailBuilderCampaign, EmailBlock
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
