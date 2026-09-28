import gzip
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from mappei import tasks as mappei_tasks
from mappei.services.scraper import (
    PRODUCT_URL_RE,
    SITEMAP_URL,
    _parse_product_page,
    _product_urls_from_sitemap,
)


class MappeiCeleryTaskTest(TestCase):
    @patch("mappei.tasks.call_command")
    def test_scrape_daily_prices_delegates_to_management_command(self, mock_call_command):
        mappei_tasks.scrape_daily_prices.run(
            product=" 104046 ",
            limit=10,
            log_file="tmp/logs/mappei.log",
        )

        mock_call_command.assert_called_once_with(
            "scrape_mappei",
            product="104046",
            limit=10,
            log_file="tmp/logs/mappei.log",
        )


class MappeiScraperParserTest(TestCase):
    def test_product_url_regex_accepts_slash_suffix_article_numbers(self):
        self.assertRegex("/de/register/194046/3", PRODUCT_URL_RE)
        self.assertRegex("/de/register/124090/00", PRODUCT_URL_RE)
        self.assertRegex("/de/register/124090", PRODUCT_URL_RE)
        self.assertRegex("/de/product/394020h", PRODUCT_URL_RE)
        self.assertRegex("/de/product/10.30303", PRODUCT_URL_RE)

    @patch("mappei.services.scraper._fetch_content")
    def test_xml_sitemap_index_reads_gzipped_product_entries(self, mock_fetch_content):
        child_url = "https://www.mappei.de/de/sitemap/products.xml.gz"
        index = f"""
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <sitemap><loc>{child_url}</loc></sitemap>
            </sitemapindex>
        """.encode()
        child = gzip.compress(
            b"""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url>
                        <loc>https://www.mappei.de/de/category/</loc>
                        <changefreq>daily</changefreq>
                    </url>
                    <url>
                        <loc>https://www.mappei.de/de/product-a/394020h</loc>
                        <changefreq>hourly</changefreq>
                    </url>
                    <url>
                        <loc>https://www.mappei.de/de/product-b/10.30303</loc>
                        <changefreq>hourly</changefreq>
                    </url>
                </urlset>
            """
        )
        mock_fetch_content.side_effect = lambda url, timeout=15: {
            SITEMAP_URL: index,
            child_url: child,
        }[url]

        self.assertEqual(
            list(_product_urls_from_sitemap()),
            [
                "https://www.mappei.de/de/product-a/394020h",
                "https://www.mappei.de/de/product-b/10.30303",
            ],
        )

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

    def test_product_parser_uses_structured_sku_and_unit_price_tiers(self):
        html = """
            <html>
                <body>
                    <h1 class="product-detail-name">Aktionsmappe</h1>
                    <span itemprop="sku">10.30303</span>
                    <span>Inhalt: 1 Stück</span>
                    <table class="product-block-prices-grid">
                        <tr class="product-block-prices-row">
                            <meta itemprop="priceFromAmount" content="1">
                            <meta itemprop="priceNetto" content="4.50">
                        </tr>
                        <tr class="product-block-prices-row">
                            <meta itemprop="priceFromAmount" content="10">
                            <meta itemprop="priceNetto" content="4.40">
                        </tr>
                    </table>
                    Beschreibung
                </body>
            </html>
        """

        data = _parse_product_page(html, "https://www.mappei.de/de/product/10.30303")

        self.assertIsNotNone(data)
        self.assertEqual(data["artikelnr"], "10.30303")
        self.assertTrue(data["hat_staffel"])
        self.assertEqual(data["preis"], Decimal("4.50"))
        self.assertEqual(data["staffelpreismenge_min"], 1)
        self.assertEqual(data["staffelpreismenge_max"], 10)
        self.assertEqual(data["staffelpreis_min"], Decimal("4.40"))
        self.assertEqual(data["staffelpreis_max"], Decimal("4.50"))
