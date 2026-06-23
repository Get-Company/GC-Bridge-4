import pytest
from django.test import SimpleTestCase
from types import SimpleNamespace


class TestMjmlComponentAdminRegistered(SimpleTestCase):
    def test_mjml_component_admin_is_registered(self):
        from django.contrib import admin
        from emails.models import MjmlComponent
        assert admin.site.is_registered(MjmlComponent)

    def test_mjml_component_admin_uses_general_component_info_field(self):
        from emails.admin import MjmlComponentAdmin

        assert "component_info" in MjmlComponentAdmin.readonly_fields
        assert "product_template_variables" not in MjmlComponentAdmin.readonly_fields

    def test_component_info_shows_children_slot_location(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import MjmlComponentAdmin
        from emails.models import MjmlComponent

        admin_instance = MjmlComponentAdmin(MjmlComponent, AdminSite())
        component = MjmlComponent(
            name="Section",
            mjml_markup="<mj-section>\n{{ children }}\n</mj-section>",
        )

        html = str(admin_instance.component_info(component))

        assert "Verschachtelung" in html
        assert "{{ children }}" in html
        assert "Zeile 2" in html
        assert "Produkt-Kontext" in html


class TestEmailCampaignComponentInline(SimpleTestCase):
    def test_component_inline_uses_unfold_sortable_ordering_field(self):
        from emails.admin import EmailCampaignComponentInline

        assert EmailCampaignComponentInline.ordering_field == "order"
        assert EmailCampaignComponentInline.hide_ordering_field is True
        assert "order" in EmailCampaignComponentInline.fields
        assert "tree_position" in EmailCampaignComponentInline.fields

    def test_tree_sorted_component_ids_put_children_after_parent(self):
        from emails.admin import _tree_sorted_component_ids

        root = SimpleNamespace(id=1, pk=1, parent_id=None, order=20)
        child = SimpleNamespace(id=2, pk=2, parent_id=1, order=10)
        grandchild = SimpleNamespace(id=3, pk=3, parent_id=2, order=10)
        other_root = SimpleNamespace(id=4, pk=4, parent_id=None, order=10)

        sorted_ids = _tree_sorted_component_ids([grandchild, child, root, other_root])

        assert sorted_ids == [4, 1, 2, 3]

    def test_tree_position_renders_depth_dashes(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import EmailCampaignComponentInline
        from emails.models import EmailCampaign

        inline = EmailCampaignComponentInline(EmailCampaign, AdminSite())
        root = SimpleNamespace(id=1, pk=1, parent=None, library_component=SimpleNamespace(name="Section"))
        child = SimpleNamespace(id=2, pk=2, parent=root, library_component=SimpleNamespace(name="Column"))
        grandchild = SimpleNamespace(
            id=3,
            pk=3,
            parent=child,
            library_component=SimpleNamespace(name="Text"),
        )

        html = str(inline.tree_position(grandchild))

        assert "--" in html
        assert "Text" in html

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
                mjml_markup="<mj-section>{{ children }}</mj-section>",
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
        assert "{{ children }}" in html
        assert "Fundstelle" in html

    def test_default_variables_info_renders_empty_state(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import EmailCampaignComponentInline
        from emails.models import EmailCampaign

        inline = EmailCampaignComponentInline(EmailCampaign, AdminSite())
        obj = SimpleNamespace(
            library_component=SimpleNamespace(default_variables={}, mjml_markup="<mj-text/>")
        )

        html = str(inline.component_default_variables(obj))

        assert "Diese Komponente setzt keine Standard-Variablen." in html
        assert "keinen" in html
        assert "{{ children }}" in html


class TestEmailCampaignProductInline(SimpleTestCase):
    def test_product_inline_uses_unfold_sortable_ordering_field(self):
        from emails.admin import EmailCampaignProductInline

        assert EmailCampaignProductInline.ordering_field == "order"
        assert EmailCampaignProductInline.hide_ordering_field is True
        assert "order" in EmailCampaignProductInline.fields


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
