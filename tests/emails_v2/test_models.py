import pytest
from emails_v2.models import EmailBuilderCampaign, EmailBlock


@pytest.mark.django_db
def test_campaign_creation():
    c = EmailBuilderCampaign.objects.create(internal_title="Test")
    assert c.status == "draft"
    assert c.created_at is not None


@pytest.mark.django_db
def test_block_tree():
    c = EmailBuilderCampaign.objects.create(internal_title="Test")
    section = EmailBlock.objects.create(campaign=c, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=c, tag="mj-column", parent=section, order=0)
    assert col.parent_id == section.id
    assert list(section.children.all()) == [col]


@pytest.mark.django_db
def test_mjml_component_has_detected_variables(db):
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(name="Test", mjml_markup="<mj-text>{{ title }}</mj-text>")
    assert hasattr(comp, "detected_variables")
    assert hasattr(comp, "variable_labels")
