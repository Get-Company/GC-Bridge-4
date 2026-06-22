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

    def test_default_variables_info_renders_empty_state(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import EmailCampaignComponentInline
        from emails.models import EmailCampaign

        inline = EmailCampaignComponentInline(EmailCampaign, AdminSite())
        obj = SimpleNamespace(library_component=SimpleNamespace(default_variables={}))

        html = str(inline.component_default_variables(obj))

        assert "Diese Komponente setzt keine Standard-Variablen." in html


class TestEmailVariableJSONForms(SimpleTestCase):
    html_json_with_escaped_quotes = (
        '{"description": "<p>hol den Sommer ins Büro</p>'
        '<p>Mit unseren <a href=\\"https://www.classei-shop.com/Fertig-Sets\\" '
        'style=\\"text-decoration: none\\"><strong style=\\"color: #ff9933;\\">'
        'Fertig-Sets</strong></a></p>"}'
    )
    html_json_with_single_quotes = (
        '{"description": "<p>hol den Sommer ins Büro</p>'
        "<p>Mit unseren <a href='https://www.classei-shop.com/Fertig-Sets' "
        "style='text-decoration: none'><strong style='color: #ff9933;'>"
        'Fertig-Sets</strong></a></p>"}'
    )

    def test_component_default_variables_accept_html_with_escaped_quotes(self):
        from emails.admin import MjmlComponentAdminForm

        field = MjmlComponentAdminForm.base_fields["default_variables"]

        cleaned = field.clean(self.html_json_with_escaped_quotes)

        assert cleaned["description"].startswith("<p>hol den Sommer ins Büro</p>")
        assert 'href="https://www.classei-shop.com/Fertig-Sets"' in cleaned["description"]

    def test_campaign_variables_accept_html_with_single_quotes(self):
        from emails.admin import EmailCampaignComponentInlineForm

        field = EmailCampaignComponentInlineForm.base_fields["variables"]

        cleaned = field.clean(self.html_json_with_single_quotes)

        assert cleaned["description"].startswith("<p>hol den Sommer ins Büro</p>")
        assert "href='https://www.classei-shop.com/Fertig-Sets'" in cleaned["description"]

    def test_json_widget_formats_saved_values_with_unicode(self):
        from emails.admin import PrettyJSONWidget

        value = {
            "description": "<p>hol den Sommer ins Büro</p>",
        }

        rendered = PrettyJSONWidget().format_value(value)

        assert "Büro" in rendered
        assert "\\u00fc" not in rendered

    def test_json_field_normalizes_line_breaks_inside_strings(self):
        from emails.admin import EmailCampaignComponentInlineForm

        field = EmailCampaignComponentInlineForm.base_fields["variables"]
        value = (
            '{"description":"<mj-text><p>hol den Sommer ins Büro - peppen Sie '
            '<strong>JETZT</strong> Ihren Arbeitsplatz und Home-Office auf.\n'
            'Classei-Ordnung in trendigen Boxen ist ein Blickfang.</p></mj-text>"}'
        )

        cleaned = field.clean(value)

        assert "Home-Office auf. Classei-Ordnung" in cleaned["description"]

    def test_json_variables_must_be_an_object(self):
        from emails.admin import MjmlComponentAdminForm

        field = MjmlComponentAdminForm.base_fields["default_variables"]

        with self.assertRaisesMessage(Exception, "gültiges JSON"):
            field.clean('{"description": "<p>ungeschlossene JSON-Struktur"')


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
