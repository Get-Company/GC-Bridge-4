import json
from decimal import Decimal
from pathlib import Path
from django.test import SimpleTestCase
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TestMjmlComponentAdminRegistered(SimpleTestCase):
    def test_mjml_component_admin_is_registered(self):
        from django.contrib import admin
        from emails.models import MjmlComponent
        assert admin.site.is_registered(MjmlComponent)

    def test_mjml_component_admin_uses_general_component_info_field(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import MjmlComponentAdmin
        from emails.models import MjmlComponent

        assert "component_info" in MjmlComponentAdmin.readonly_fields
        assert "product_template_variables" not in MjmlComponentAdmin.readonly_fields
        admin_instance = MjmlComponentAdmin(MjmlComponent, AdminSite())
        assert admin_instance.ordering_field == "order"
        assert admin_instance.hide_ordering_field is True
        assert admin_instance.get_ordering(None) == ("order", "name")

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
        assert "Empfaenger-" in html
        assert "Kunden-Kontext" in html
        assert "recipient.email" in html
        assert "customer.erp_nr" in html


class TestEmailCampaignAdmin(SimpleTestCase):
    def test_campaign_admin_does_not_expose_component_inlines(self):
        from emails.admin import EmailCampaignAdmin

        assert EmailCampaignAdmin.inlines == ()

    def test_new_campaigns_default_to_simple_editor(self):
        from emails.models import EmailCampaign

        campaign = EmailCampaign(internal_title="Test")

        assert campaign.layout_mode == EmailCampaign.LayoutMode.SIMPLE

    def test_campaign_admin_displays_and_filters_categories(self):
        from django.contrib.admin.sites import AdminSite

        from emails.admin import EmailCampaignAdmin, EmailCampaignCategoryAdmin
        from emails.models import EmailCampaign, EmailCampaignCategory

        campaign_admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
        category_admin = EmailCampaignCategoryAdmin(EmailCampaignCategory, AdminSite())
        campaign = SimpleNamespace(
            categories=SimpleNamespace(
                all=lambda: [SimpleNamespace(name="Shop"), SimpleNamespace(name="Newsletter")]
            )
        )

        assert "categories" in campaign_admin.list_filter
        assert "categories" in campaign_admin.autocomplete_fields
        assert "preview_recipient" in campaign_admin.autocomplete_fields
        assert "categories" not in campaign_admin.filter_horizontal
        assert campaign_admin.category_list(campaign) == "Shop, Newsletter"
        assert category_admin.search_fields == ("name",)
        assert category_admin.get_ordering(None) == ("name",)

    def test_component_campaign_links_to_simple_editor(self):
        from django.contrib.admin.sites import AdminSite

        from emails.admin import EmailCampaignAdmin
        from emails.models import EmailCampaign

        campaign_admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
        campaign = SimpleNamespace(
            pk=42,
            layout_mode=EmailCampaign.LayoutMode.COMPONENTS,
            preview_recipient=SimpleNamespace(email="preview@example.com"),
        )

        list_link = str(campaign_admin.editor_link(campaign))
        editor_actions = str(campaign_admin.simple_editor_link(campaign))

        assert "/admin/emails/emailcampaign/42/editor/" in list_link
        assert "Öffnen" in list_link
        assert "/admin/emails/emailcampaign/42/editor/" in editor_actions
        assert "Einfachen Editor öffnen" in editor_actions
        assert "preview@example.com" in editor_actions

    @patch("emails.admin._copy_component_products_to_simple")
    def test_component_campaign_is_converted_to_simple_layout(
        self,
        copy_component_products,
    ):
        from django.contrib.admin.sites import AdminSite

        from emails.admin import EmailCampaignAdmin
        from emails.models import EmailCampaign

        campaign = SimpleNamespace(
            layout_mode=EmailCampaign.LayoutMode.COMPONENTS,
            save=Mock(),
        )
        campaign_admin = EmailCampaignAdmin(EmailCampaign, AdminSite())

        result = campaign_admin._ensure_simple_layout(campaign)

        assert result is campaign
        assert campaign.layout_mode == EmailCampaign.LayoutMode.SIMPLE
        copy_component_products.assert_called_once_with(campaign, campaign)
        campaign.save.assert_called_once_with(update_fields=["layout_mode"])

    def test_simple_campaign_editor_shows_selected_preview_recipient(self):
        from django.contrib.admin.sites import AdminSite

        from emails.admin import EmailCampaignAdmin
        from emails.models import EmailCampaign

        campaign_admin = EmailCampaignAdmin(EmailCampaign, AdminSite())
        campaign = SimpleNamespace(
            pk=7,
            layout_mode=EmailCampaign.LayoutMode.SIMPLE,
            preview_recipient=SimpleNamespace(email="simple@example.com"),
        )

        editor_actions = str(campaign_admin.simple_editor_link(campaign))

        assert "/admin/emails/emailcampaign/7/editor/" in editor_actions
        assert "Einfachen Editor öffnen" in editor_actions
        assert "simple@example.com" in editor_actions

    def test_campaign_export_modal_has_copyable_mjml_output(self):
        template = Path("templates/admin/emails/emailcampaign/change_form.html").read_text(
            encoding="utf-8"
        )

        assert 'id="mjml-output"' in template
        assert "data.mjml" in template
        assert "function copyMjml()" in template
        assert 'id="text-output"' in template
        assert "data.text" in template
        assert "function copyText()" in template
        assert "Vorschau mit Empfänger" in template
        assert "original.preview_recipient.email" in template
        assert "original.components.count" not in template

    @patch("emails.admin.EmailCampaignProduct.objects.get_or_create")
    def test_component_products_are_preserved_when_switching_to_simple_editor(
        self,
        get_or_create_campaign_product,
    ):
        from emails.admin import _copy_component_products_to_simple

        linked_product = SimpleNamespace(
            product_id=17,
            special_price_override=Decimal("12.34"),
            discount_pct=None,
        )
        components = [
            SimpleNamespace(
                product_id=11,
                campaign_product=None,
                order=10,
            ),
            SimpleNamespace(
                product_id=None,
                campaign_product=linked_product,
                order=20,
            ),
        ]
        source_components = SimpleNamespace(
            select_related=lambda *args: SimpleNamespace(
                filter=lambda **kwargs: SimpleNamespace(
                    order_by=lambda *fields: components
                )
            )
        )
        target_products = SimpleNamespace(
            values_list=lambda *args, **kwargs: [],
        )
        source_campaign = SimpleNamespace(components=source_components)
        target_campaign = SimpleNamespace(campaign_products=target_products)
        get_or_create_campaign_product.side_effect = [
            (SimpleNamespace(), True),
            (SimpleNamespace(), True),
        ]

        created = _copy_component_products_to_simple(source_campaign, target_campaign)

        assert created == 2
        assert get_or_create_campaign_product.call_count == 2
        assert get_or_create_campaign_product.call_args_list[0].kwargs == {
            "campaign": target_campaign,
            "product_id": 11,
            "defaults": {
                "special_price_override": None,
                "discount_pct": None,
                "prices_synced_at": None,
                "order": 10,
            },
        }
        assert get_or_create_campaign_product.call_args_list[1].kwargs == {
            "campaign": target_campaign,
            "product_id": 17,
            "defaults": {
                "special_price_override": Decimal("12.34"),
                "discount_pct": None,
                "prices_synced_at": None,
                "order": 20,
            },
        }

    def test_campaign_admin_shows_recipient_customer_context_info(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import EmailCampaignAdmin
        from emails.models import EmailCampaign

        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())
        html = str(admin_instance.campaign_context_info(EmailCampaign(internal_title="Test")))

        assert "recipient.email" in html
        assert "recipient.salutation_display_name" in html
        assert "customer.erp_nr" in html

    @patch("emails.admin.html_to_plain_text", return_value="Preview text")
    @patch("emails.admin.compile_mjml_to_html", return_value="<html>Preview</html>")
    @patch("emails.admin.render_campaign_mjml", return_value="<mjml>Preview</mjml>")
    @patch("emails.admin.EmailCampaign")
    def test_export_html_view_renders_preview_with_selected_recipient(
        self,
        campaign_model,
        render_campaign_mjml,
        compile_mjml_to_html,
        html_to_plain_text,
    ):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from emails.admin import EmailCampaignAdmin
        from emails.models import EmailCampaign

        preview_recipient = SimpleNamespace(email="preview@example.com")
        campaign = SimpleNamespace(
            pk=1,
            internal_title="Kampagne",
            preview_recipient=preview_recipient,
        )
        campaign_model.objects.get.return_value = campaign

        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())
        request = RequestFactory().get("/admin/emails/emailcampaign/1/export-html/")
        response = admin_instance.export_html_view(request, campaign_id=1)

        assert response.status_code == 200
        render_campaign_mjml.assert_called_once_with(campaign, recipient=preview_recipient)
        compile_mjml_to_html.assert_called_once_with("<mjml>Preview</mjml>")
        html_to_plain_text.assert_called_once_with("<html>Preview</html>")
        assert json.loads(response.content) == {
            "html": "<html>Preview</html>",
            "mjml": "<mjml>Preview</mjml>",
            "text": "Preview text",
        }

    @patch("emails.admin.compile_mjml_to_html", return_value="<html>Preview</html>")
    @patch("emails.simple_editor.build_simple_mjml", return_value="<mjml>Preview</mjml>")
    def test_simple_editor_preview_uses_selected_recipient(
        self,
        build_simple_mjml,
        compile_mjml_to_html,
    ):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from emails.admin import EmailCampaignAdmin
        from emails.models import EmailCampaign

        preview_recipient = SimpleNamespace(email="preview@example.com")
        campaign = SimpleNamespace(pk=1, preview_recipient=preview_recipient)
        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())
        admin_instance._editor_campaign = lambda request, campaign_id: campaign
        request = RequestFactory().post(
            "/admin/emails/emailcampaign/1/editor/preview/",
            data=json.dumps({"headline": "Test"}),
            content_type="application/json",
        )

        response = admin_instance.simple_editor_preview_view(request, campaign_id=1)

        assert response.status_code == 200
        build_simple_mjml.assert_called_once_with(
            campaign,
            recipient=preview_recipient,
            override={"headline": "Test"},
        )
        assert json.loads(response.content) == {"html": "<html>Preview</html>"}


class TestEmailSmtpSettingsAdmin(SimpleTestCase):
    def test_smtp_settings_admin_is_registered_as_singleton(self):
        from django.contrib import admin

        from emails.admin import EmailSmtpSettingsAdmin
        from emails.models import EmailSmtpSettings

        assert admin.site.is_registered(EmailSmtpSettings)
        assert EmailSmtpSettingsAdmin.actions_detail == ("test_smtp_connection",)
        admin_instance = EmailSmtpSettingsAdmin(EmailSmtpSettings, admin.site)
        assert admin_instance.has_add_permission(None) is False
        assert admin_instance.has_delete_permission(None) is False


class TestEmailCampaignComponentInline(SimpleTestCase):
    def test_component_inline_uses_unfold_sortable_ordering_field(self):
        from django.contrib.admin.sites import AdminSite
        from emails.admin import EmailCampaignComponentInline
        from emails.models import EmailCampaign

        inline = EmailCampaignComponentInline(EmailCampaign, AdminSite())
        inline_fields = tuple(
            field
            for _title, options in EmailCampaignComponentInline.fieldsets
            for field in options["fields"]
        )
        assert inline.ordering_field == "order"
        assert inline.hide_ordering_field is True
        assert "order" in inline_fields
        assert "tree_position" in inline_fields
        assert "product" in inline_fields
        assert "special_price_override" not in inline_fields
        assert "discount_pct" not in inline_fields
        assert "campaign_product" not in inline_fields

    def test_component_inline_autocompletes_products_directly(self):
        from emails.admin import EmailCampaignComponentInline

        assert "product" in EmailCampaignComponentInline.autocomplete_fields

    def test_component_form_initializes_product_from_legacy_campaign_product(self):
        from emails.admin import EmailCampaignComponentInlineForm
        from emails.models import EmailCampaignComponent, EmailCampaignProduct

        legacy_campaign_product = EmailCampaignProduct(
            product_id=12,
        )
        component = EmailCampaignComponent(campaign_product=legacy_campaign_product)
        form = EmailCampaignComponentInlineForm(
            instance=component
        )

        assert form.initial["product"] == 12

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
        root = SimpleNamespace(id=1, pk=1, parent=None, order=10, title="", library_component=SimpleNamespace(name="Section"))
        child = SimpleNamespace(id=2, pk=2, parent=root, order=20, title="", library_component=SimpleNamespace(name="Column"))
        grandchild = SimpleNamespace(
            id=3,
            pk=3,
            parent=child,
            order=30,
            title="Eigener Titel",
            library_component=SimpleNamespace(name="Text"),
        )

        html = str(inline.tree_position(grandchild))

        assert "--" in html
        assert "30" in html
        assert "drag_indicator" in html
        assert "Eigener Titel" in html

    def test_default_variables_info_field_is_shown_with_campaign_variables(self):
        from emails.admin import EmailCampaignComponentInline

        inline_fields = tuple(
            field
            for _title, options in EmailCampaignComponentInline.fieldsets
            for field in options["fields"]
        )
        assert "component_default_variables" in inline_fields
        assert inline_fields.index("variables") < inline_fields.index(
            "component_default_variables"
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

    def test_campaign_variables_use_json_editor_widget(self):
        from django.test import override_settings
        from django_json_widget.widgets import JSONEditorWidget
        from emails.admin import EmailCampaignComponentInlineForm

        value = {
            "description": "<p>hol den Sommer ins Büro</p>",
        }

        widget = EmailCampaignComponentInlineForm.base_fields["variables"].widget
        rendered = widget.render("variables", value, attrs={"id": "id_variables"})

        assert isinstance(widget, JSONEditorWidget)
        assert '"mode": "code"' in rendered
        assert "JSONEditor" in rendered
        assert "description" in rendered
        with override_settings(
            STORAGES={
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                }
            }
        ):
            assert "dist/jsoneditor.min.js" in str(widget.media)

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

    def test_component_markup_reports_jinja_syntax_errors(self):
        from emails.admin import MjmlComponentAdminForm

        form = MjmlComponentAdminForm(
            data={
                "name": "Ungültig",
                "description": "",
                "mjml_markup": "{{ product. }}",
                "rendering_mode": "jinja",
                "placement": "body",
                "order": "0",
                "default_variables": "{}",
            }
        )

        assert not form.is_valid()
        assert "Jinja-Template-Syntax in Zeile 1" in str(form.errors["mjml_markup"])

    def test_component_markup_allows_shopware_syntax_in_passthrough_mode(self):
        from emails.admin import MjmlComponentAdminForm

        form = MjmlComponentAdminForm(
            data={
                "name": "Shopware",
                "description": "",
                "mjml_markup": "{{ product. }}",
                "rendering_mode": "shopware",
                "placement": "body",
                "order": "0",
                "default_variables": "{}",
            }
        )

        assert form.is_valid(), form.errors


class TestEmailCampaignQueueEntryAdmin(SimpleTestCase):
    def test_queue_admin_shows_rendered_html_preview_only(self):
        from emails.admin import EmailCampaignQueueEntryAdmin

        rendered_fields = EmailCampaignQueueEntryAdmin.fieldsets[2][1]["fields"]

        assert rendered_fields == ("rendered_html_preview",)
        assert "rendered_html_preview" in EmailCampaignQueueEntryAdmin.readonly_fields
        assert "rendered_html" not in EmailCampaignQueueEntryAdmin.readonly_fields
        assert "rendered_mjml" not in EmailCampaignQueueEntryAdmin.readonly_fields

    def test_rendered_html_preview_uses_iframe_srcdoc(self):
        from django.contrib.admin.sites import AdminSite

        from emails.admin import EmailCampaignQueueEntryAdmin
        from emails.models import EmailCampaignQueueEntry

        admin_instance = EmailCampaignQueueEntryAdmin(EmailCampaignQueueEntry, AdminSite())
        obj = SimpleNamespace(rendered_html="<html><body><h1>Hallo</h1></body></html>")

        html = str(admin_instance.rendered_html_preview(obj))

        assert "<iframe" in html
        assert "srcdoc=" in html
        assert "&lt;h1&gt;Hallo&lt;/h1&gt;" in html
