import pytest
from django.test import SimpleTestCase
from types import SimpleNamespace


class TestMjmlComponentAdminRegistered(SimpleTestCase):
    def test_mjml_component_admin_is_registered(self):
        from django.contrib import admin
        from emails.models import MjmlComponent
        assert admin.site.is_registered(MjmlComponent)


class TestEmailCampaignComponentInline(SimpleTestCase):
    def test_default_variables_info_field_is_shown_before_campaign_variables(self):
        from emails.admin import EmailCampaignComponentInline

        assert "component_default_variables" in EmailCampaignComponentInline.fields
        assert (
            EmailCampaignComponentInline.fields.index("component_default_variables")
            < EmailCampaignComponentInline.fields.index("variables")
        )

    def test_default_variables_info_renders_component_defaults(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import EmailCampaignComponentInline
        from emails.models import EmailCampaign

        inline = EmailCampaignComponentInline(EmailCampaign, AdminSite())
        obj = SimpleNamespace(
            library_component=SimpleNamespace(
                default_variables={
                    "h1-title": "Standardtitel",
                    "h1-small": "Standardunterzeile",
                }
            )
        )

        html = str(inline.component_default_variables(obj))

        assert "Diese Werte kommen aus der Komponente" in html
        assert "h1-title" in html
        assert "Standardtitel" in html
        assert "h1-small" in html
        assert "Standardunterzeile" in html


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
