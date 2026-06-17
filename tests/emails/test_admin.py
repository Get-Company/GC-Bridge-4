import pytest
from django.test import SimpleTestCase


class TestMjmlComponentAdminRegistered(SimpleTestCase):
    def test_mjml_component_admin_is_registered(self):
        from django.contrib import admin
        from emails.models import MjmlComponent
        assert admin.site.is_registered(MjmlComponent)


@pytest.mark.django_db
class TestEmailCampaignAdminDefaultComponents:
    def test_default_components_created_on_new_campaign(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        from emails.admin import EmailCampaignAdmin
        from django.contrib.admin.sites import AdminSite

        MjmlComponent.objects.create(name="Logo", placement="body", is_default=True, order=10)
        MjmlComponent.objects.create(name="Footer", placement="body", is_default=True, order=20)

        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())
        campaign = EmailCampaign.objects.create(internal_title="Test", status="draft")
        admin_instance._ensure_default_components(campaign)

        assert EmailCampaignComponent.objects.filter(campaign=campaign).count() == 2
        names = list(
            EmailCampaignComponent.objects.filter(campaign=campaign)
            .select_related("library_component")
            .values_list("library_component__name", flat=True)
            .order_by("order")
        )
        assert names == ["Logo", "Footer"]

    def test_default_components_not_duplicated_on_second_call(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        from emails.admin import EmailCampaignAdmin
        from django.contrib.admin.sites import AdminSite

        MjmlComponent.objects.create(name="Logo", placement="body", is_default=True, order=10)
        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())
        campaign = EmailCampaign.objects.create(internal_title="Test2", status="draft")
        admin_instance._ensure_default_components(campaign)
        admin_instance._ensure_default_components(campaign)

        assert EmailCampaignComponent.objects.filter(campaign=campaign).count() == 1
