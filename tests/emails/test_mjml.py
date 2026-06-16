import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from types import SimpleNamespace

from emails.mjml import ProductEmailProxy, render_campaign_mjml, compile_mjml_to_html


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
    def __init__(self, price, sales_channel_id=1, is_default=True):
        self.price = price
        self.sales_channel_id = sales_channel_id
        self.sales_channel = SimpleNamespace(is_default=is_default)

    def get_current_price(self, *, as_float=False):
        return self.price


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
        product = MagicMock()
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.email_special_price is None

    def test_discount_pct_calculated_correctly(self):
        product = MagicMock()
        product.price = Decimal("10.00")
        proxy = ProductEmailProxy(product, special_price_override=Decimal("8.00"))
        assert proxy.discount_pct == 20

    def test_discount_pct_is_zero_without_override(self):
        product = MagicMock()
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.discount_pct == 0

    def test_shipping_cost_is_free_delegates_to_product(self):
        product = MagicMock()
        product.get_shipping_cost.return_value = 0
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is True

    def test_shipping_cost_is_free_false_when_cost_exists(self):
        product = MagicMock()
        product.get_shipping_cost.return_value = 5.95
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is False

    def test_shipping_cost_is_free_falls_back_to_price_when_no_method(self):
        product = MagicMock(spec=["price"])
        product.price = Decimal("99.00")
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is True

    def test_shipping_cost_is_free_false_for_low_price_without_method(self):
        product = MagicMock(spec=["price"])
        product.price = Decimal("50.00")
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


@pytest.mark.django_db
class TestRenderCampaignMjml:
    def test_renders_without_products(self):
        from emails.models import EmailCampaign
        campaign = EmailCampaign.objects.create(
            internal_title="Test",
            h1="Testtitel",
            h1_small="Untertitel",
            intro_text="<p>Einleitung</p>",
            product_template="product",
            status="draft",
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mjml>" in mjml
        assert "Testtitel" in mjml
        assert "Einleitung" in mjml

    def test_product_template_selection_shipping_free(self):
        from emails.models import EmailCampaign
        campaign = EmailCampaign.objects.create(
            internal_title="Test2",
            h1="Test",
            product_template="product_shipping_free",
            status="draft",
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mjml>" in mjml

    def test_proxy_discount_pct_correct(self):
        from decimal import Decimal
        from emails.mjml import ProductEmailProxy
        from unittest.mock import MagicMock

        product = MagicMock()
        product.price = Decimal("10.00")
        proxy = ProductEmailProxy(product, special_price_override=Decimal("8.00"))
        assert proxy.discount_pct == 20
        assert proxy.email_special_price == Decimal("8.00")
