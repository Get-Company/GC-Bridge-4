from decimal import Decimal
from unittest import TestCase

from mappei.services.scraper import PRODUCT_URL_RE, _parse_product_page


class MappeiScraperParserTest(TestCase):
    def test_product_url_regex_accepts_slash_suffix_article_numbers(self):
        self.assertRegex("/de/register/194046/3", PRODUCT_URL_RE)
        self.assertRegex("/de/register/124090/00", PRODUCT_URL_RE)
        self.assertRegex("/de/register/124090", PRODUCT_URL_RE)

    def test_product_parser_preserves_slash_suffix_article_numbers(self):
        html = """
            <html>
                <body>
                    <h1 class="product-detail-name">Register</h1>
                    Produktnummer: 194046/3 Inhalt: 100 Stück
                    12,34 € Brutto 14,68 € Beschreibung
                </body>
            </html>
        """

        data = _parse_product_page(html, "https://www.mappei.de/de/register/194046/3")

        self.assertIsNotNone(data)
        self.assertEqual(data["artikelnr"], "194046/3")
        self.assertEqual(data["preis"], Decimal("12.34"))

    def test_product_parser_preserves_double_zero_slash_suffix_article_numbers(self):
        html = """
            <html>
                <body>
                    <h1 class="product-detail-name">Register</h1>
                    Produktnummer: 124090/00 Inhalt: 100 Stück
                    10,00 € Brutto 11,90 € Beschreibung
                </body>
            </html>
        """

        data = _parse_product_page(html, "https://www.mappei.de/de/register/124090/00")

        self.assertIsNotNone(data)
        self.assertEqual(data["artikelnr"], "124090/00")
        self.assertEqual(data["preis"], Decimal("10.00"))
