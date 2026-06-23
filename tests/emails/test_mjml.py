import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock
from types import SimpleNamespace

from emails.mjml import (
    ProductEmailProxy,
    campaign_offer_context,
    compile_mjml_to_html,
    render_campaign_mjml,
)


class FakePriceQuerySet:
    def __init__(self, entries):
        self.entries = list(entries)

    def all(self):
        return self

    def filter(self, **kwargs):
        entries = self.entries
        if "sales_channel_id__in" in kwargs:
            channel_ids = set(kwargs["sales_channel_id__in"])
            entries = [entry for entry in entries if entry.sales_channel_id in channel_ids]
        if kwargs.get("sales_channel__is_default") is True:
            entries = [entry for entry in entries if entry.sales_channel.is_default]
        return type(self)(entries)

    def order_by(self, *args):
        return self

    def first(self):
        return self.entries[0] if self.entries else None


class FakePrice:
    def __init__(
        self,
        price,
        sales_channel_id=1,
        is_default=True,
        special_price=None,
        special_end_date=None,
    ):
        self.price = price
        self.special_price = special_price
        self.special_end_date = special_end_date
        self.sales_channel_id = sales_channel_id
        self.sales_channel = SimpleNamespace(is_default=is_default)

    def get_standard_price(self, *, as_float=False):
        return self.price

    def get_special_price(self, *, as_float=False):
        return self.special_price

    def get_current_price(self, *, as_float=False):
        return self.special_price or self.price


class FakeQuerySet:
    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def __iter__(self):
        return iter(self.entries)

    def filter(self, **kwargs):
        entries = self.entries
        if kwargs.get("enabled") is True:
            entries = [entry for entry in entries if entry.enabled]
        return type(self)(entries)

    def order_by(self, *args):
        return type(self)(sorted(self.entries, key=lambda entry: (getattr(entry, "order", 0), id(entry))))

    def select_related(self, *args):
        return self

    def values_list(self, *args, **kwargs):
        return []


class TestProductEmailProxy:
    def test_delegates_attribute_to_product(self):
        product = MagicMock()
        product.name = "Testprodukt"
        product.erp_nr = "710001"
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.name == "Testprodukt"
        assert proxy.erp_nr == "710001"

    def test_override_returns_email_special_price(self):
        product = MagicMock()
        proxy = ProductEmailProxy(product, special_price_override=Decimal("9.90"))
        assert proxy.email_special_price == Decimal("9.90")

    def test_no_override_returns_none_for_email_special_price(self):
        product = SimpleNamespace()
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.email_special_price is None

    def test_uses_product_special_price(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("10.00"), sales_channel_id=1, is_default=True, special_price=Decimal("8.50")),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.price == Decimal("10.00")
        assert proxy.email_special_price == Decimal("8.50")
        assert proxy.current_price == Decimal("8.50")
        assert proxy.discount_pct == 15

    def test_legacy_price_methods_delegate_to_product_prices(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("10.00"), sales_channel_id=1, is_default=True, special_price=Decimal("8.50")),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=None)

        assert proxy.get_list_price() == Decimal("10.00")
        assert proxy.get_special_price() == Decimal("8.50")
        assert proxy.get_current_price() == Decimal("8.50")
        assert proxy.get_shipping_cost() is None

    def test_discount_pct_calculated_correctly(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("10.00"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=Decimal("8.00"))
        assert proxy.discount_pct == 20

    def test_discount_pct_override_calculates_email_special_price(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("10.00"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, discount_pct=Decimal("15.00"))
        assert proxy.email_special_price == Decimal("8.50")
        assert proxy.discount_pct == 15

    def test_discount_pct_is_zero_without_override(self):
        product = SimpleNamespace()
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.discount_pct == 0

    def test_shipping_cost_is_free_for_high_current_price(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("100.00"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is True

    def test_shipping_cost_is_free_false_for_low_current_price(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("50.00"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is False

    def test_shipping_cost_is_free_false_without_product_price_attribute(self):
        product = SimpleNamespace()
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is False

    def test_price_uses_default_sales_channel_price_entry(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("123.45"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.price == Decimal("123.45")

    def test_current_price_uses_email_special_price_before_list_price(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("123.45"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=Decimal("99.00"))
        assert proxy.price == Decimal("123.45")
        assert proxy.current_price == Decimal("99.00")

    def test_special_end_date_uses_selected_price_entry(self):
        special_end_date = datetime(2026, 7, 31)
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(
                    Decimal("123.45"),
                    sales_channel_id=1,
                    is_default=True,
                    special_end_date=special_end_date,
                ),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.special_end_date == special_end_date

    def test_campaign_offer_context_ignores_end_date_without_special_price(self):
        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(
                    Decimal("123.45"),
                    sales_channel_id=1,
                    is_default=True,
                    special_price=None,
                    special_end_date=datetime(2026, 7, 31),
                ),
            ])
        )
        context = campaign_offer_context([ProductEmailProxy(product)])
        assert context["special_price"] is False
        assert context["special_end_date"] is None
        assert context["offer_valid_until_text"] == ""


class TestCompileMjmlToHtml:
    def test_uses_installed_mjml_binary_when_available(self, monkeypatch):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            with open(command[3], "w", encoding="utf-8") as html_file:
                html_file.write("<html>compiled</html>")

        monkeypatch.setattr("emails.mjml.shutil.which", lambda command: "/usr/local/bin/mjml")
        monkeypatch.setattr("emails.mjml.subprocess.run", fake_run)

        html = compile_mjml_to_html("<mjml></mjml>")

        assert html == "<html>compiled</html>"
        assert calls[0][0] == "mjml"

    def test_falls_back_to_npx_when_mjml_binary_is_missing(self, monkeypatch):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            with open(command[4], "w", encoding="utf-8") as html_file:
                html_file.write("<html>compiled</html>")

        monkeypatch.setattr("emails.mjml.shutil.which", lambda command: None)
        monkeypatch.setattr("emails.mjml.subprocess.run", fake_run)

        html = compile_mjml_to_html("<mjml></mjml>")

        assert html == "<html>compiled</html>"
        assert calls[0][:2] == ["npx", "mjml"]


class TestCampaignComponentRendering:
    def test_render_campaign_uses_enabled_component_order(self, monkeypatch):
        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context["body_mjml"]
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        def make_comp(name, markup, order, enabled=True):
            lib = SimpleNamespace(placement="body", name=name, mjml_markup=markup)
            return SimpleNamespace(
                library_component=lib,
                library_component_id=True,
                title="", body_html="",
                order=order,
                enabled=enabled,
            )

        campaign = SimpleNamespace(
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([
                make_comp("Content", "content_text", order=20),
                make_comp("Logo", "logo", order=10, enabled=False),
                make_comp("Header", "header_nav", order=5),
            ]),
        )

        mjml = render_campaign_mjml(campaign)
        assert mjml == "header_nav\ncontent_text"

    def test_render_campaign_supports_hyphenated_component_variables(self, monkeypatch):
        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context["body_mjml"]
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        lib = SimpleNamespace(
            placement="body",
            name="Headline",
            mjml_markup=(
                "<mj-section><mj-column><mj-text>"
                "<h1>{{ h1-title }}</h1><small>{{ h1-small }}</small>"
                "</mj-text></mj-column></mj-section>"
            ),
        )
        component = SimpleNamespace(
            library_component=lib,
            library_component_id=True,
            variables={
                "h1-title": "Hol den Sommer ins Büro",
                "h1-small": "...alles aus langweilig",
            },
            order=10,
            enabled=True,
        )
        campaign = SimpleNamespace(
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([component]),
        )

        mjml = render_campaign_mjml(campaign)
        assert "Hol den Sommer ins Büro" in mjml
        assert "...alles aus langweilig" in mjml

    def test_render_campaign_uses_library_component_default_variables(self, monkeypatch):
        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context["body_mjml"]
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        lib = SimpleNamespace(
            placement="body",
            name="Headline",
            mjml_markup="<mj-section><mj-column><mj-text>{{ title }}</mj-text></mj-column></mj-section>",
            default_variables={"title": "Standardtitel"},
        )
        component = SimpleNamespace(
            library_component=lib,
            library_component_id=True,
            variables={},
            order=10,
            enabled=True,
        )
        campaign = SimpleNamespace(
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([component]),
        )

        mjml = render_campaign_mjml(campaign)
        assert "Standardtitel" in mjml

    def test_render_campaign_component_variables_override_defaults(self, monkeypatch):
        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context["body_mjml"]
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        lib = SimpleNamespace(
            placement="body",
            name="Headline",
            mjml_markup="<mj-section><mj-column><mj-text>{{ title }}</mj-text></mj-column></mj-section>",
            default_variables={"title": "Standardtitel"},
        )
        component = SimpleNamespace(
            library_component=lib,
            library_component_id=True,
            variables={"title": "Kampagnentitel"},
            order=10,
            enabled=True,
        )
        campaign = SimpleNamespace(
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([component]),
        )

        mjml = render_campaign_mjml(campaign)
        assert "Kampagnentitel" in mjml
        assert "Standardtitel" not in mjml

    def test_render_campaign_exposes_latest_offer_valid_until_text(self, monkeypatch):
        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context["body_mjml"]
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        product_a = SimpleNamespace(
            name="Produkt A",
            prices=FakePriceQuerySet([
                FakePrice(
                    Decimal("10.00"),
                    special_price=Decimal("8.00"),
                    special_end_date=datetime(2026, 7, 15),
                ),
            ]),
        )
        product_b = SimpleNamespace(
            name="Produkt B",
            prices=FakePriceQuerySet([
                FakePrice(
                    Decimal("20.00"),
                    special_price=Decimal("16.00"),
                    special_end_date=datetime(2026, 7, 31),
                ),
            ]),
        )

        def make_comp(component_id, product):
            return SimpleNamespace(
                id=component_id,
                pk=component_id,
                parent_id=None,
                library_component=SimpleNamespace(
                    placement="body",
                    name=f"Produkt {component_id}",
                    mjml_markup=(
                        "<mj-text>{% if special_price and offer_valid_until_text %}"
                        "{{ offer_valid_until_text }} / {{ special_end_date|format_date }}"
                        "{% endif %}</mj-text>"
                    ),
                    default_variables={},
                ),
                library_component_id=True,
                product=product,
                campaign_product_id=None,
                variables={},
                order=component_id * 10,
                enabled=True,
            )

        campaign = SimpleNamespace(
            components=FakeQuerySet([
                make_comp(1, product_a),
                make_comp(2, product_b),
            ]),
        )

        mjml = render_campaign_mjml(campaign)

        assert "Angebot gültig bis 31.07.2026" in mjml
        assert "31.07.2026" in mjml
        assert "15.07.2026" not in mjml


@pytest.mark.django_db
class TestMjmlComponent:
    def test_str_returns_name(self):
        from emails.models import MjmlComponent
        component = MjmlComponent(name="Logo", placement="body", mjml_markup="<mj-section/>", order=10)
        assert str(component) == "Logo"

    def test_default_placement_is_body(self):
        from emails.models import MjmlComponent
        component = MjmlComponent(name="Test")
        assert component.placement == "body"

    def test_default_variables_defaults_to_dict(self):
        from emails.models import MjmlComponent
        component = MjmlComponent(name="Test")
        assert component.default_variables == {}


@pytest.mark.django_db
class TestEmailCampaignComponentStr:
    def test_str_shows_order_name_and_placement(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        lib = MjmlComponent.objects.create(name="Logo", placement="body", order=10)
        campaign = EmailCampaign.objects.create(internal_title="T", status="draft")
        comp = EmailCampaignComponent(
            campaign=campaign,
            library_component=lib,
            order=10,
        )
        assert str(comp) == "10 – Logo (Body (Inhaltsbereich))"


@pytest.mark.django_db
class TestRenderCampaignMjml:
    def test_renders_with_body_component(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        lib = MjmlComponent.objects.create(
            name="Titel",
            placement="body",
            mjml_markup="<mj-section><mj-column><mj-text>{{ title }}</mj-text></mj-column></mj-section>",
        )
        campaign = EmailCampaign.objects.create(internal_title="Test", status="draft")
        EmailCampaignComponent.objects.create(
            campaign=campaign,
            library_component=lib,
            variables={"title": "Testtitel"},
            order=10,
            enabled=True,
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mjml>" in mjml
        assert "Testtitel" in mjml

    def test_head_component_lands_in_mj_head(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        lib = MjmlComponent.objects.create(
            name="CSS",
            placement="head",
            mjml_markup="<mj-style>.custom{}</mj-style>",
        )
        campaign = EmailCampaign.objects.create(internal_title="HeadTest", status="draft")
        EmailCampaignComponent.objects.create(
            campaign=campaign,
            library_component=lib,
            order=5,
            enabled=True,
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mj-head>" in mjml
        assert ".custom{}" in mjml

    def test_proxy_discount_pct_correct(self):
        from decimal import Decimal
        from emails.mjml import ProductEmailProxy

        product = SimpleNamespace(
            prices=FakePriceQuerySet([
                FakePrice(Decimal("10.00"), sales_channel_id=1, is_default=True),
            ])
        )
        proxy = ProductEmailProxy(product, special_price_override=Decimal("8.00"))
        assert proxy.discount_pct == 20
        assert proxy.email_special_price == Decimal("8.00")


class TestEmailCampaignProductFields:
    def test_discount_pct_and_prices_synced_at_exist(self):
        from emails.models import EmailCampaignProduct
        # Just check the fields exist on the class
        assert hasattr(EmailCampaignProduct, "discount_pct")
        assert hasattr(EmailCampaignProduct, "prices_synced_at")


class TestHeadBodySplit:
    def test_component_product_is_rendered_directly(self, monkeypatch):
        from emails.mjml import render_campaign_mjml

        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context.get("body_mjml", "")
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())
        product = SimpleNamespace(
            name="Direktes Produkt",
            erp_nr="710001",
            prices=FakePriceQuerySet([
                FakePrice(Decimal("12.50"), sales_channel_id=1, is_default=True),
            ]),
            get_images=lambda: [],
        )
        component = SimpleNamespace(
            id=1,
            pk=1,
            parent_id=None,
            library_component=SimpleNamespace(
                placement="body",
                name="Produkt",
                mjml_markup="<mj-text>{{ product.name }} / {{ product.price|format_price }}</mj-text>",
                default_variables={},
            ),
            library_component_id=True,
            product=product,
            campaign_product_id=None,
            variables={},
            order=10,
            enabled=True,
        )
        campaign = SimpleNamespace(
            components=FakeQuerySet([component]),
        )

        mjml = render_campaign_mjml(campaign)

        assert "Direktes Produkt / 12.50" in mjml

    def test_nested_components_render_into_parent_children_slot(self, monkeypatch):
        from emails.mjml import render_campaign_mjml

        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context.get("body_mjml", "")
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        def make_comp(component_id, name, markup, order, parent_id=None, variables=None):
            return SimpleNamespace(
                id=component_id,
                pk=component_id,
                parent_id=parent_id,
                library_component=SimpleNamespace(
                    placement="body",
                    name=name,
                    mjml_markup=markup,
                    default_variables={},
                ),
                library_component_id=True,
                campaign_product_id=None,
                variables=variables or {},
                order=order,
                enabled=True,
            )

        section = make_comp(1, "Section", "<mj-section>{{ children }}</mj-section>", 10)
        column = make_comp(2, "Column", "<mj-column>{{ children }}</mj-column>", 10, parent_id=1)
        text_top = make_comp(
            3,
            "Text",
            "<mj-text>{{ content }}</mj-text>",
            10,
            parent_id=2,
            variables={"content": "Erster Text"},
        )
        image = make_comp(
            4,
            "Image",
            '<mj-image src="{{ src }}" />',
            20,
            parent_id=2,
            variables={"src": "https://example.com/bild.jpg"},
        )
        text_bottom = make_comp(
            5,
            "Text",
            "<mj-text>{{ content }}</mj-text>",
            30,
            parent_id=2,
            variables={"content": "Zweiter Text"},
        )
        campaign = SimpleNamespace(
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([text_bottom, image, text_top, column, section]),
        )

        mjml = render_campaign_mjml(campaign)

        assert mjml.startswith("<mj-section><mj-column>")
        assert mjml.endswith("</mj-column></mj-section>")
        assert mjml.index("Erster Text") < mjml.index("bild.jpg") < mjml.index("Zweiter Text")

    def test_head_components_land_in_head_mjml(self, monkeypatch):
        from types import SimpleNamespace
        from emails.mjml import render_campaign_mjml

        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return f"HEAD:{context.get('head_mjml', '')}|BODY:{context.get('body_mjml', '')}"
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)
        monkeypatch.setattr("emails.mjml._campaign_sales_channel_ids", lambda campaign: ())

        def make_comp(placement, markup, order, enabled=True):
            lib = SimpleNamespace(placement=placement, name=f"Comp-{order}", mjml_markup=markup)
            return SimpleNamespace(
                library_component=lib,
                library_component_id=True,
                title="", subtitle="", body_html="",
                order=order,
                enabled=enabled,
            )

        campaign = SimpleNamespace(
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([
                make_comp("head", "<mj-style>body{}</mj-style>", order=5),
                make_comp("body", "<mj-section/>", order=10),
            ]),
        )

        result = render_campaign_mjml(campaign)
        head_part = result.split("|")[0].replace("HEAD:", "")
        body_part = result.split("|")[1].replace("BODY:", "")
        assert "<mj-style>body{}</mj-style>" in head_part
        assert "<mj-section/>" in body_part
        assert "<mj-style>body{}</mj-style>" not in body_part
