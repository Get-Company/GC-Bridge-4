import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from emails.mjml import ProductEmailProxy, render_campaign_mjml, compile_mjml_to_html


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

    def test_product_template_selection(self):
        from emails.models import EmailCampaign
        campaign = EmailCampaign.objects.create(
            internal_title="Test2",
            h1="Test",
            product_template="product_shipping_free",
            status="draft",
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mjml>" in mjml
