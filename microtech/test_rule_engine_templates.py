from django.test import TestCase
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.templates import render_template


class _Order:
    nr = "4711"
    firma = ""
    name = "Mustermann GmbH"
    anrede = "mrs"
    billing_country_code = "DE"
    vat_id = ""
    customer_group = ""


class TemplateTest(TestCase):
    def setUp(self):
        self.ctx = EvaluationContext(_Order())

    def test_plain_literal(self):
        self.assertEqual(render_template("Webshop-Kunde", self.ctx), "Webshop-Kunde")

    def test_single_variable(self):
        self.assertEqual(render_template("{{ nr }}", self.ctx), "4711")

    def test_fallback_chain_picks_first_non_empty(self):
        self.assertEqual(render_template("{{ firma | name }}", self.ctx), "Mustermann GmbH")

    def test_transform_applied(self):
        self.assertEqual(render_template("{{ anrede | anrede_de }}", self.ctx), "Frau")

    def test_named_resolver(self):
        self.assertEqual(render_template("{{ @steuerkategorie }}", self.ctx), "1")

    def test_mixed_literal_and_variable(self):
        self.assertEqual(render_template("Auftrag {{ nr }}", self.ctx), "Auftrag 4711")
