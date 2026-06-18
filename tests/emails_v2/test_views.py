import pytest
from django.test import Client
from django.contrib.auth.models import User
from emails_v2.models import EmailBuilderCampaign


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user("staff", password="pw", is_staff=True)
    client = Client()
    client.login(username="staff", password="pw")
    return client


@pytest.mark.django_db
def test_campaign_list_requires_staff(client):
    response = client.get("/email-builder/")
    assert response.status_code == 302  # redirects to login


@pytest.mark.django_db
def test_campaign_list_accessible_for_staff(staff_client):
    response = staff_client.get("/email-builder/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_campaign_create_post(staff_client):
    response = staff_client.post("/email-builder/campaign/create/", {"internal_title": "My Campaign"})
    assert response.status_code == 302
    assert EmailBuilderCampaign.objects.filter(internal_title="My Campaign").exists()


@pytest.mark.django_db
def test_editor_view(staff_client):
    c = EmailBuilderCampaign.objects.create(internal_title="Ed")
    response = staff_client.get(f"/email-builder/campaign/{c.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_htmx_block_create(staff_client):
    c = EmailBuilderCampaign.objects.create(internal_title="Htmx")
    response = staff_client.post(
        "/email-builder/htmx/block/create/",
        {"campaign_id": c.pk, "tag": "mj-section"},
    )
    assert response.status_code == 200
    from emails_v2.models import EmailBlock
    assert EmailBlock.objects.filter(campaign=c, tag="mj-section").exists()


@pytest.mark.django_db
def test_htmx_block_create_appends_content_to_existing_section_column(staff_client):
    from emails_v2.models import EmailBlock

    c = EmailBuilderCampaign.objects.create(internal_title="Section Content")
    section = EmailBlock.objects.create(campaign=c, tag="mj-section", order=0)
    column = EmailBlock.objects.create(campaign=c, tag="mj-column", parent=section, order=0)

    response = staff_client.post(
        "/email-builder/htmx/block/create/",
        {"campaign_id": c.pk, "tag": "mj-text", "parent_id": section.pk},
    )

    assert response.status_code == 200
    assert EmailBlock.objects.filter(campaign=c, tag="mj-column", parent=section).count() == 1
    text = EmailBlock.objects.get(campaign=c, tag="mj-text")
    assert text.parent == column
