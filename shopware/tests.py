from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from products.models import (
    Category,
    Image,
    Price,
    Product,
    ProductImage,
    ProductProperty,
    ProductVariantAttribute,
    ProductVariantFamily,
    PropertyGroup,
    PropertyValue,
    Storage,
)
from shopware.management.commands.shopware_sync_products import (
    Command as ShopwareSyncProductsCommand,
    _build_product_sync_payload,
)
from shopware.management.commands.shopware_force_product_image_uploads import Command as ForceProductImageUploadsCommand
from shopware.models import ShopwareSettings
from shopware.services.order import OrderService
from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService
from shopware.services.shopware5 import Shopware5APIError, Shopware5ProductSyncService
from shopware.services.shopware5_category_mapping import (
    Shopware5CategoryMappingService,
    Shopware5CategoryMappingSnapshot,
)
from shopware.services.shopware5_duplicate_category_merge import Shopware5DuplicateCategoryTreeMergeService
from shopware.services.shopware6 import Criteria, EqualsFilter, InvalidTokenError, Shopware6Service
from shopware.services.variant_sync import ShopwareVariantSyncService


class Shopware6ProductStockPayloadTest(SimpleTestCase):
    def test_payload_uses_integer_shopware_stock(self):
        prices = MagicMock()
        prices.select_related.return_value.all.return_value = []
        product = SimpleNamespace(
            erp_nr="581001",
            is_active=True,
            tax=None,
            name="Mappe A4",
            name_de="",
            name_en="",
            description=None,
            storage=SimpleNamespace(get_shopware_stock=91),
            prices=prices,
        )

        payload = _build_product_sync_payload(
            product=product,
            effective_sku="",
            default_channel=None,
            channels=[],
            admin_user_id=None,
            content_type_id=None,
        )

        self.assertEqual(payload["stock"], 91)


class ShopwareVariantStockPayloadTest(SimpleTestCase):
    def test_child_payload_uses_effective_shopware_stock(self):
        product_service = MagicMock()
        resolution = SimpleNamespace(
            variants=(
                SimpleNamespace(
                    product=SimpleNamespace(
                        pk=1,
                        erp_nr="581001",
                        storage=Storage(stock=Decimal("9.59"), virtual_stock=0),
                    ),
                    option_values=(SimpleNamespace(pk=10),),
                ),
                SimpleNamespace(
                    product=SimpleNamespace(
                        pk=2,
                        erp_nr="581002",
                        storage=Storage(stock=Decimal("99"), virtual_stock=7),
                    ),
                    option_values=(SimpleNamespace(pk=20),),
                ),
            )
        )

        ShopwareVariantSyncService(product_service=product_service)._upsert_children(
            resolution=resolution,
            parent_id="parent-shopware-id",
            child_ids={1: "child-one", 2: "child-two"},
            value_ids={10: "option-one", 20: "option-two"},
        )

        product_service.bulk_upsert.assert_called_once_with(
            [
                {
                    "id": "child-one",
                    "productNumber": "581001",
                    "parentId": "parent-shopware-id",
                    "stock": 9,
                    "options": [{"id": "option-one"}],
                },
                {
                    "id": "child-two",
                    "productNumber": "581002",
                    "parentId": "parent-shopware-id",
                    "stock": 7,
                    "options": [{"id": "option-two"}],
                },
            ]
        )


class Shopware6CustomSearchKeywordsPayloadTest(SimpleTestCase):
    def _product(self, mappei_products):
        prices = MagicMock()
        prices.select_related.return_value.all.return_value = []
        mappei_products_manager = MagicMock()
        mappei_products_manager.all.return_value = mappei_products
        return SimpleNamespace(
            erp_nr="581001",
            is_active=True,
            tax=None,
            name="Mappe A4",
            name_de="",
            name_en="",
            description=None,
            storage=SimpleNamespace(get_shopware_stock=1),
            prices=prices,
            mappei_products=mappei_products_manager,
        )

    def _payload(self, product):
        return _build_product_sync_payload(
            product=product,
            effective_sku="",
            default_channel=None,
            channels=[],
            admin_user_id=None,
            content_type_id=None,
        )

    def test_payload_includes_mappei_number_and_name_deduplicated(self):
        product = self._product(
            [
                SimpleNamespace(artikelnr="M-100", name="Mappei Ordner"),
                SimpleNamespace(artikelnr="M-200", name=""),
                SimpleNamespace(artikelnr="M-100", name="Mappei Ordner"),
            ]
        )

        payload = self._payload(product)

        self.assertEqual(
            payload["customSearchKeywords"],
            ["M-100", "Mappei Ordner", "M-200"],
        )

    def test_payload_omits_keywords_without_mappei_link(self):
        payload = self._payload(self._product([]))

        self.assertNotIn("customSearchKeywords", payload)


class Shopware6ServiceTokenRetryTest(SimpleTestCase):
    @patch("shopware.services.shopware6.Shopware6AdminAPIClientBase")
    def test_request_post_retries_once_on_invalid_token(self, client_factory):
        first_client = MagicMock()
        second_client = MagicMock()
        first_client.request_post.side_effect = InvalidTokenError()
        second_client.request_post.return_value = {"ok": True}
        client_factory.side_effect = [first_client, second_client]

        service = Shopware6Service()
        result = service.request_post("/search/product", payload={"limit": 1})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client_factory.call_count, 2)
        first_client.request_post.assert_called_once_with(
            "/search/product",
            payload={"limit": 1},
            additional_query_params=None,
        )
        second_client.request_post.assert_called_once_with(
            "/search/product",
            payload={"limit": 1},
            additional_query_params=None,
        )

    def test_request_post_strips_empty_criteria_values_recursively(self):
        client = MagicMock()
        client.request_post.return_value = {"ok": True}
        service = Shopware6Service.__new__(Shopware6Service)
        service.client = client

        criteria = Criteria(limit=10)
        criteria.associations["stateMachineState"] = Criteria()
        criteria.associations["orderCustomer"] = Criteria()
        criteria.associations["orderCustomer"].associations["customer"] = Criteria()
        criteria.filter.append(EqualsFilter(field="stateMachineState.technicalName", value="open"))

        result = service.request_post("/search/order", payload=criteria)

        self.assertEqual(result, {"ok": True})
        client.request_post.assert_called_once_with(
            "/search/order",
            payload={
                "limit": 10,
                "associations": {
                    "stateMachineState": {},
                    "orderCustomer": {
                        "associations": {
                            "customer": {},
                        },
                    },
                },
                "filter": [
                    {
                        "field": "stateMachineState.technicalName",
                        "value": "open",
                        "type": "equals",
                    },
                ],
            },
            additional_query_params=None,
        )


class Shopware5ProductSyncServiceTest(SimpleTestCase):
    def test_configured_shop_url_is_normalized_to_shopware_api_url(self):
        service = Shopware5ProductSyncService(
            settings_obj=SimpleNamespace(
                api_url="https://www.classei-shop.com/",
                username="user",
                api_token="token",
            ),
            session=MagicMock(),
        )

        self.assertEqual(service.base_url, "https://www.classei-shop.com/api")

    def test_configured_api_url_is_not_duplicated(self):
        service = Shopware5ProductSyncService(
            settings_obj=SimpleNamespace(
                api_url="https://www.classei-shop.com/api/",
                username="user",
                api_token="token",
            ),
            session=MagicMock(),
        )

        self.assertEqual(service.base_url, "https://www.classei-shop.com/api")

    def test_default_session_uses_digest_auth_like_legacy_client(self):
        service = Shopware5ProductSyncService(
            settings_obj=SimpleNamespace(
                api_url="https://www.classei-shop.com/api",
                username="user",
                api_token="token",
            ),
        )

        self.assertIsInstance(service.session.auth, HTTPDigestAuth)

    def test_request_retries_once_with_basic_auth_after_auth_rejection(self):
        first_response = MagicMock()
        first_response.status_code = 401
        first_response.request = SimpleNamespace(
            url="https://www.classei-shop.com/api/articles/091300?useNumberAsId=true",
            headers={"Authorization": "Digest username=\"user\""},
        )
        first_response.json.return_value = {"success": False}
        second_response = MagicMock()
        second_response.status_code = 200
        second_response.request = SimpleNamespace(
            url="https://www.classei-shop.com/api/articles/091300?useNumberAsId=true",
            headers={"Authorization": "Basic abc"},
        )
        second_response.json.return_value = {"success": True, "data": {"id": 123}}
        session = MagicMock()
        session.request.side_effect = [first_response, second_response]
        service = Shopware5ProductSyncService(
            settings_obj=SimpleNamespace(
                api_url="https://www.classei-shop.com/api",
                username="user",
                api_token="token",
            ),
            session=session,
        )

        result = service.get_article_by_number("091300")

        self.assertEqual(result["id"], 123)
        self.assertEqual(session.request.call_count, 2)
        self.assertNotIn("auth", session.request.call_args_list[0].kwargs)
        self.assertIsInstance(session.request.call_args_list[1].kwargs["auth"], HTTPBasicAuth)

    def test_get_article_by_number_uses_inline_use_number_query_like_legacy_client(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"success": True, "data": {"id": 123, "number": "091300"}}
        session = MagicMock()
        session.request.return_value = response
        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=session)
        service.base_url = "https://www.classei-shop.com/api"

        article = service.get_article_by_number("091300")

        self.assertEqual(article["id"], 123)
        session.request.assert_called_once_with(
            method="GET",
            url="https://www.classei-shop.com/api/articles/091300?useNumberAsId=true",
            json=None,
            timeout=service.timeout_seconds,
        )

    def test_build_product_payload_updates_active_stock_factor_and_group_prices(self):
        price = SimpleNamespace(
            price=Decimal("10.00"),
            rebate_quantity=None,
            rebate_price=None,
            special_price=None,
            is_special_active=False,
            sales_channel=SimpleNamespace(is_default=True, is_active=True),
        )
        product = SimpleNamespace(
            erp_nr="581000",
            name="Mappe A4",
            description_short="Kurztext",
            description="Langtext.",
            is_active=False,
            purchase_unit=5,
            min_purchase=10,
            unit="% Stck",
            factor=3,
            storage=SimpleNamespace(get_shopware_stock=42),
            prefetched_prices_for_shopware_sync=[price],
        )

        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=MagicMock())
        payload = service.build_product_payload(product)

        self.assertFalse(payload["active"])
        self.assertFalse(payload["is_active"])
        self.assertEqual(payload["name"], "Mappe A4")
        self.assertEqual(payload["description"], "Kurztext")
        self.assertEqual(payload["descriptionLong"], "Langtext.")
        self.assertEqual(payload["mainDetail"]["inStock"], 42)
        self.assertEqual(payload["mainDetail"]["maxPurchase"], 10000)
        self.assertEqual(payload["mainDetail"]["minPurchase"], 10)
        self.assertEqual(payload["mainDetail"]["purchaseSteps"], 5)
        self.assertEqual(payload["mainDetail"]["packUnit"], "Stck")
        self.assertEqual(payload["mainDetail"]["gcFaktor"], 3)
        prices = payload["mainDetail"]["prices"]
        self.assertIn(
            {
                "customerGroupKey": "CHB2C",
                "from": 1,
                "to": "beliebig",
                "price": 13.0,
                "pseudoPrice": None,
            },
            prices,
        )
        self.assertIn(
            {
                "customerGroupKey": "IT_de",
                "from": 1,
                "to": "beliebig",
                "price": 10.45,
                "pseudoPrice": None,
            },
            prices,
        )

    def test_build_product_payload_uses_special_price_as_price_and_standard_as_pseudo_price(self):
        price = SimpleNamespace(
            price=Decimal("10.00"),
            rebate_quantity=None,
            rebate_price=None,
            special_price=Decimal("8.00"),
            is_special_active=True,
            sales_channel=SimpleNamespace(is_default=True, is_active=True),
        )
        product = SimpleNamespace(
            erp_nr="581000",
            is_active=True,
            purchase_unit=1,
            min_purchase=1,
            unit="Stck",
            factor=None,
            storage=SimpleNamespace(get_shopware_stock=5),
            prefetched_prices_for_shopware_sync=[price],
        )

        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=MagicMock())
        payload = service.build_product_payload(product)

        self.assertTrue(payload["active"])
        self.assertTrue(payload["is_active"])
        self.assertIn(
            {
                "customerGroupKey": "Vk0",
                "from": 1,
                "to": "beliebig",
                "price": 8.0,
                "pseudoPrice": 10.0,
            },
            payload["mainDetail"]["prices"],
        )

    def test_build_product_payload_prefers_german_translation_fields_for_texts(self):
        product = SimpleNamespace(
            erp_nr="581000",
            name="Alter Name",
            name_de="Neuer Name",
            description_short="Alter Kurztext",
            description_short_de="<p>Neuer Kurztext</p>",
            description="Alter Langtext",
            description_de="<p>Neuer Langtext</p>",
            is_active=True,
            purchase_unit=1,
            min_purchase=1,
            unit="Stck",
            factor=None,
            storage=SimpleNamespace(get_shopware_stock=5),
            prefetched_prices_for_shopware_sync=[],
        )

        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=MagicMock())
        payload = service.build_product_payload(product)

        self.assertEqual(payload["name"], "Neuer Name")
        self.assertEqual(payload["description"], "<p>Neuer Kurztext</p>")
        self.assertEqual(payload["descriptionLong"], "<p>Neuer Langtext</p>")

    def test_build_product_payload_keeps_base_texts_when_translation_fields_are_empty(self):
        product = SimpleNamespace(
            erp_nr="581000",
            name="Basis Name",
            name_de="",
            description_short="Basis Kurztext",
            description_short_de="",
            description="Basis Langtext",
            description_de="",
            is_active=True,
            purchase_unit=1,
            min_purchase=1,
            unit="Stck",
            factor=None,
            storage=SimpleNamespace(get_shopware_stock=5),
            prefetched_prices_for_shopware_sync=[],
        )

        service = Shopware5ProductSyncService(settings_obj=SimpleNamespace(is_active=False), session=MagicMock())
        payload = service.build_product_payload(product)

        self.assertEqual(payload["name"], "Basis Name")
        self.assertEqual(payload["description"], "Basis Kurztext")
        self.assertEqual(payload["descriptionLong"], "Basis Langtext")


class Shopware5CategoryMappingServiceTest(SimpleTestCase):
    class FakeShopware5Api:
        categories = [
            {"id": 1, "parentId": None, "name": "Root", "position": 0, "active": True},
            {"id": 851, "parentId": 1, "name": "Deutsch", "position": 0, "active": True},
            {"id": 852, "parentId": 851, "name": "Orga-Mappen", "position": 0, "active": True},
            {"id": 1006, "parentId": 1, "name": "Schweiz", "position": 1, "active": True},
            {"id": 1007, "parentId": 1006, "name": "Orga-Mappen", "position": 0, "active": True},
            {"id": 1074, "parentId": 1, "name": "Italien", "position": 2, "active": True},
            {"id": 1075, "parentId": 1074, "name": "Orga-Mappen", "position": 0, "active": True},
        ]
        article_rows = [{"id": 100}, {"id": 101}, {"id": 102}]
        article_details = {
            "100": {
                "id": 100,
                "mainDetail": {"number": "100001"},
                "details": [{"number": "100001-ROT"}],
                "categories": [{"id": 852}, {"id": 1007}, {"id": 1075}],
            },
            "101": {
                "id": 101,
                "mainDetail": {"number": "200001"},
                "details": [],
                "categories": [{"id": 852}],
            },
            "102": {
                "id": 102,
                "mainDetail": None,
                "details": [],
                "categories": [{"id": 852}],
            },
        }

        def __init__(self):
            self.paths = []

        def get(self, path):
            self.paths.append(path)
            if path.startswith("/categories?"):
                return {"success": True, "total": len(self.categories), "data": self.categories}
            if path.startswith("/articles?"):
                return {"success": True, "total": len(self.article_rows), "data": self.article_rows}
            article_id = path.rsplit("/", 1)[-1]
            return {"success": True, "data": self.article_details[article_id]}

    def test_collect_snapshot_limits_categories_to_deutsch_and_schweiz(self):
        api = self.FakeShopware5Api()
        snapshot = Shopware5CategoryMappingService(api_service=api).collect_snapshot()

        self.assertEqual(set(snapshot.categories), {"851", "852", "1006", "1007"})
        self.assertEqual(snapshot.root_ids, ("851", "1006"))
        self.assertEqual(snapshot.product_numbers_by_category["852"], {"100001", "100001-ROT", "200001"})
        self.assertEqual(snapshot.product_numbers_by_category["1007"], {"100001", "100001-ROT"})
        self.assertEqual(snapshot.product_numbers_by_category["851"], set())
        self.assertEqual(snapshot.article_count, 3)
        self.assertEqual(snapshot.article_detail_count, 3)
        self.assertIn("/articles/100", api.paths)
        self.assertIn("/articles/102", api.paths)

    def test_collect_snapshot_can_skip_an_inactive_subtree(self):
        api = self.FakeShopware5Api()
        api.categories = [
            *api.categories,
            {"id": 853, "parentId": 851, "name": "Inaktiv", "position": 1, "active": False},
            {"id": 854, "parentId": 853, "name": "Aktives Kind", "position": 0, "active": True},
        ]

        snapshot = Shopware5CategoryMappingService(api_service=api).collect_snapshot(
            skip_inactive_categories=True
        )

        self.assertEqual(set(snapshot.categories), {"851", "852", "1006", "1007"})
        self.assertEqual(snapshot.skipped_inactive_category_count, 2)

    def test_preview_reports_paths_and_assignment_counts_for_every_category(self):
        snapshot = Shopware5CategoryMappingService(api_service=self.FakeShopware5Api()).collect_snapshot()

        preview = Shopware5CategoryMappingService(api_service=self.FakeShopware5Api()).preview(snapshot)

        self.assertEqual(preview["roots"], ["Deutsch", "Schweiz"])
        self.assertEqual(preview["categories"], 4)
        self.assertEqual(preview["assignments"], 5)
        self.assertEqual(
            preview["category_reports"],
            [
                {
                    "id": "851",
                    "name": "Deutsch",
                    "path": "Deutsch",
                    "position": 0,
                    "active": True,
                    "product_count": 0,
                },
                {
                    "id": "852",
                    "name": "Orga-Mappen",
                    "path": "Deutsch > Orga-Mappen",
                    "position": 0,
                    "active": True,
                    "product_count": 3,
                },
                {
                    "id": "1006",
                    "name": "Schweiz",
                    "path": "Schweiz",
                    "position": 1,
                    "active": True,
                    "product_count": 0,
                },
                {
                    "id": "1007",
                    "name": "Orga-Mappen",
                    "path": "Schweiz > Orga-Mappen",
                    "position": 0,
                    "active": True,
                    "product_count": 2,
                },
            ],
        )


class Shopware5CategoryMappingApplyTest(TestCase):
    def test_apply_reuses_matching_tree_and_replaces_stale_assignments_when_requested(self):
        deutsch = Category.objects.create(name="Deutsch", slug="deutsch", sort_order=0)
        mappen = Category.objects.create(name="Orga-Mappen", slug="orga-mappen", parent=deutsch, sort_order=0)
        assigned_product = Product.objects.create(erp_nr="100001", name="Zuzuordnender Artikel")
        stale_product = Product.objects.create(erp_nr="999999", name="Veralteter Artikel")
        stale_product.categories.add(mappen)
        snapshot = Shopware5CategoryMappingSnapshot(
            categories={
                "851": {"id": "851", "parent_id": "1", "name": "Deutsch", "position": 0, "active": True},
                "852": {
                    "id": "852",
                    "parent_id": "851",
                    "name": "Orga-Mappen",
                    "position": 0,
                    "active": True,
                },
            },
            root_ids=("851",),
            product_numbers_by_category={"851": set(), "852": {"100001"}},
            article_count=1,
            article_detail_count=1,
        )

        service = Shopware5CategoryMappingService(api_service=MagicMock())
        comparison = service.preview_category_comparison(
            snapshot,
            root_name="Deutsch",
            category_name="Orga-Mappen",
        )

        self.assertEqual(comparison["source_category"]["sw5_id"], "852")
        self.assertEqual(comparison["local_category"]["id"], mappen.pk)
        self.assertEqual(comparison["missing_assignment"], ["100001"])
        self.assertEqual(comparison["missing_in_project"], [])

        result = service.apply(
            snapshot,
            replace_assignments=True,
        )

        deutsch.refresh_from_db()
        mappen.refresh_from_db()
        self.assertEqual((deutsch.sw5_id, mappen.sw5_id), ("851", "852"))
        self.assertIsNone(deutsch.parent)
        self.assertEqual(mappen.parent, deutsch)
        self.assertEqual(list(assigned_product.categories.values_list("pk", flat=True)), [mappen.pk])
        self.assertFalse(stale_product.categories.exists())
        self.assertEqual(result["created_categories"], 0)
        self.assertEqual(result["created_assignments"], 1)
        self.assertEqual(result["removed_assignments"], 1)
        reconciliation = service.preview_reconciliation_report(snapshot)
        reports_by_id = {report["id"]: report for report in reconciliation["reports"]}
        self.assertEqual(reconciliation["recognized_categories"], 2)
        self.assertTrue(reports_by_id["851"]["parent_matches"])
        self.assertTrue(reports_by_id["852"]["parent_matches"])
        self.assertTrue(reports_by_id["852"]["position_matches"])
        self.assertEqual(reports_by_id["852"]["assigned_products"], 1)
        self.assertEqual(reports_by_id["852"]["missing_assignment"], [])

    def test_apply_matches_identical_subtrees_by_full_path_and_ignores_sw6_level_four(self):
        deutsch = Category.objects.create(name="Deutsch", slug="deutsch", sort_order=0)
        schweiz = Category.objects.create(name="Schweiz", slug="schweiz", sort_order=1)
        deutsch_orga = Category.objects.create(
            name="Orga-Mappen",
            slug="deutsch-orga-mappen",
            parent=deutsch,
            sort_order=0,
        )
        schweiz_orga = Category.objects.create(
            name="Orga-Mappen",
            slug="schweiz-orga-mappen",
            parent=schweiz,
            sort_order=0,
        )
        deutsch_standard = Category.objects.create(
            name="Standard-Mappen",
            slug="deutsch-standard-mappen",
            parent=deutsch_orga,
            sort_order=0,
        )
        schweiz_standard = Category.objects.create(
            name="Standard-Mappen",
            slug="schweiz-standard-mappen",
            parent=schweiz_orga,
            sort_order=0,
        )
        sw6_only_child = Category.objects.create(
            name="SW6-Unterkategorie",
            slug="sw6-unterkategorie",
            parent=deutsch_standard,
            sw6_id="sw6-only-child",
            sort_order=0,
        )
        snapshot = Shopware5CategoryMappingSnapshot(
            categories={
                "851": {"id": "851", "parent_id": "1", "name": "Deutsch", "position": 0, "active": True},
                "852": {
                    "id": "852",
                    "parent_id": "851",
                    "name": "Orga-Mappen",
                    "position": 0,
                    "active": True,
                },
                "860": {
                    "id": "860",
                    "parent_id": "852",
                    "name": "Standard-Mappen",
                    "position": 0,
                    "active": True,
                },
                "1006": {"id": "1006", "parent_id": "1", "name": "Schweiz", "position": 1, "active": True},
                "1007": {
                    "id": "1007",
                    "parent_id": "1006",
                    "name": "Orga-Mappen",
                    "position": 0,
                    "active": True,
                },
                "1014": {
                    "id": "1014",
                    "parent_id": "1007",
                    "name": "Standard-Mappen",
                    "position": 0,
                    "active": True,
                },
            },
            root_ids=("851", "1006"),
            product_numbers_by_category={
                "851": set(),
                "852": set(),
                "860": set(),
                "1006": set(),
                "1007": set(),
                "1014": set(),
            },
            article_count=0,
            article_detail_count=0,
        )

        result = Shopware5CategoryMappingService(api_service=MagicMock()).apply(snapshot)

        deutsch_standard.refresh_from_db()
        schweiz_standard.refresh_from_db()
        sw6_only_child.refresh_from_db()
        self.assertEqual(deutsch_standard.sw5_id, "860")
        self.assertEqual(schweiz_standard.sw5_id, "1014")
        self.assertEqual(sw6_only_child.sw5_id, None)
        self.assertEqual(sw6_only_child.parent, deutsch_standard)
        self.assertEqual(result["created_categories"], 0)

    def test_apply_refuses_to_create_a_category_when_no_full_path_matches(self):
        Category.objects.create(name="Deutsch", slug="deutsch", sort_order=0)
        snapshot = Shopware5CategoryMappingSnapshot(
            categories={
                "851": {"id": "851", "parent_id": "1", "name": "Deutsch", "position": 0, "active": True},
                "852": {
                    "id": "852",
                    "parent_id": "851",
                    "name": "Orga-Mappen",
                    "position": 0,
                    "active": True,
                },
            },
            root_ids=("851",),
            product_numbers_by_category={"851": set(), "852": set()},
            article_count=0,
            article_detail_count=0,
        )

        with self.assertRaisesMessage(Shopware5APIError, "vollstaendigen Shopware-5-Pfad"):
            Shopware5CategoryMappingService(api_service=MagicMock()).apply(snapshot)

        self.assertEqual(Category.objects.count(), 1)

    def test_apply_preserves_shopware5_sibling_positions_in_the_mptt_tree(self):
        deutsch = Category.objects.create(name="Deutsch", slug="deutsch", sort_order=0)
        Category.objects.create(
            name="Zuerst im Namen, zuletzt in SW5",
            slug="zuerst-im-namen",
            parent=deutsch,
            sort_order=1000,
        )
        Category.objects.create(name="Mitte", slug="mitte", parent=deutsch, sort_order=1000)
        Category.objects.create(
            name="Zuletzt im Namen, zuerst in SW5",
            slug="zuletzt-im-namen",
            parent=deutsch,
            sort_order=1000,
        )
        snapshot = Shopware5CategoryMappingSnapshot(
            categories={
                "851": {"id": "851", "parent_id": "1", "name": "Deutsch", "position": 0, "active": True},
                "901": {
                    "id": "901",
                    "parent_id": "851",
                    "name": "Zuerst im Namen, zuletzt in SW5",
                    "position": 30,
                    "active": True,
                },
                "902": {
                    "id": "902",
                    "parent_id": "851",
                    "name": "Mitte",
                    "position": 20,
                    "active": True,
                },
                "903": {
                    "id": "903",
                    "parent_id": "851",
                    "name": "Zuletzt im Namen, zuerst in SW5",
                    "position": 10,
                    "active": True,
                },
            },
            root_ids=("851",),
            product_numbers_by_category={"851": set(), "901": set(), "902": set(), "903": set()},
            article_count=0,
            article_detail_count=0,
        )

        Shopware5CategoryMappingService(api_service=MagicMock()).apply(snapshot)

        deutsch = Category.objects.get(sw5_id="851")
        self.assertEqual(
            list(deutsch.get_children().order_by("lft").values_list("sw5_id", "sort_order")),
            [("903", 10), ("902", 20), ("901", 30)],
        )


class Shopware5CategoryIdMappingTest(TestCase):
    def test_maps_only_sw5_ids_by_complete_path_and_reports_missing_paths(self):
        deutsch = Category.objects.create(name="Deutsch", slug="sw6-deutsch", sw6_id="sw6-de", sort_order=70)
        orga = Category.objects.create(
            name="Orga-Mappen",
            slug="sw6-deutsch-orga",
            sw6_id="sw6-orga",
            parent=deutsch,
            sort_order=80,
        )
        product = Product.objects.create(erp_nr="100001", name="SW6-Zuordnung")
        product.categories.add(orga)
        snapshot = Shopware5CategoryMappingSnapshot(
            categories={
                "851": {"id": "851", "parent_id": "1", "name": "Deutsch", "position": 0, "active": True},
                "852": {
                    "id": "852",
                    "parent_id": "851",
                    "name": "Orga-Mappen",
                    "position": 0,
                    "active": True,
                },
                "853": {
                    "id": "853",
                    "parent_id": "851",
                    "name": "In SW6 entfernt",
                    "position": 1,
                    "active": True,
                },
            },
            root_ids=("851",),
            product_numbers_by_category={"851": set(), "852": set(), "853": set()},
            article_count=0,
            article_detail_count=0,
        )
        service = Shopware5CategoryMappingService(api_service=MagicMock())

        preview = service.preview_sw5_id_mapping(snapshot)
        result = service.apply_sw5_ids(snapshot)

        deutsch.refresh_from_db()
        orga.refresh_from_db()
        self.assertEqual(result["mapped"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(deutsch.sw5_id, "851")
        self.assertEqual(orga.sw5_id, "852")
        self.assertEqual((deutsch.sort_order, orga.sort_order), (70, 80))
        self.assertEqual(list(product.categories.values_list("pk", flat=True)), [orga.pk])
        self.assertEqual(
            next(report["status"] for report in preview["reports"] if report["sw5_id"] == "853"),
            "missing_local_category",
        )


class Shopware5DuplicateCategoryTreeMergeServiceTest(TestCase):
    def setUp(self):
        self.technical_root = Category.objects.create(name="Root", slug="technical-root", sw5_id="1", sort_order=0)
        self.duplicate_deutsch = Category.objects.create(
            name="Deutsch",
            slug="duplicate-deutsch",
            parent=self.technical_root,
            sw5_id="851",
            sort_order=10,
        )
        self.duplicate_orga = Category.objects.create(
            name="Orga-Mappen",
            slug="duplicate-deutsch-orga",
            parent=self.duplicate_deutsch,
            sw5_id="852",
            sort_order=20,
        )
        self.deutsch = Category.objects.create(name="Deutsch", slug="deutsch", sort_order=30)
        self.orga = Category.objects.create(
            name="Orga-Mappen",
            slug="deutsch-orga",
            parent=self.deutsch,
            sort_order=40,
        )
        self.product = Product.objects.create(erp_nr="100001", name="Nur im Duplikat")
        self.product.categories.add(self.duplicate_orga)

    def test_transfers_only_sw5_ids_to_the_matching_canonical_tree(self):
        service = Shopware5DuplicateCategoryTreeMergeService()

        preview = service.preview(root_names=("Deutsch",))
        result = service.apply(root_names=("Deutsch",))

        self.assertTrue(preview["can_apply"])
        self.assertEqual(len(preview["transfers"]), 2)
        self.assertEqual(result["transferred_sw5_ids"], 2)
        self.duplicate_deutsch.refresh_from_db()
        self.duplicate_orga.refresh_from_db()
        self.deutsch.refresh_from_db()
        self.orga.refresh_from_db()
        self.product.refresh_from_db()
        self.assertIsNone(self.duplicate_deutsch.sw5_id)
        self.assertIsNone(self.duplicate_orga.sw5_id)
        self.assertEqual(self.deutsch.sw5_id, "851")
        self.assertEqual(self.orga.sw5_id, "852")
        self.assertEqual(self.deutsch.parent, None)
        self.assertEqual(self.orga.parent, self.deutsch)
        self.assertEqual((self.deutsch.sort_order, self.orga.sort_order), (30, 40))
        self.assertEqual(list(self.product.categories.values_list("pk", flat=True)), [self.duplicate_orga.pk])

    def test_deletion_is_an_explicit_second_step(self):
        service = Shopware5DuplicateCategoryTreeMergeService()
        service.apply(root_names=("Deutsch",))

        result = service.apply(root_names=("Deutsch",), delete_duplicate_subtrees=True)

        self.assertEqual(result["deleted_categories"], 3)
        self.assertTrue(result["technical_root_deleted"])
        self.assertFalse(Category.objects.filter(pk=self.technical_root.pk).exists())
        self.assertTrue(Category.objects.filter(pk=self.deutsch.pk, sw5_id="851").exists())
        self.assertTrue(Category.objects.filter(pk=self.orga.pk, sw5_id="852").exists())


class Shopware5SyncProductsCommandTest(TestCase):
    @patch("shopware.management.commands.shopware5_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware5_sync_products.Shopware5ProductSyncService")
    def test_raises_command_error_when_batch_contains_errors(self, service_cls, runtime_start):
        Product.objects.create(erp_nr="581000", name="Mappe A4")
        runtime = MagicMock()
        runtime_start.return_value = runtime
        service_cls.return_value.sync_products.return_value = {
            "processed": 1,
            "success": 0,
            "errors": 1,
            "skipped": 0,
        }

        with self.assertRaisesMessage(CommandError, "Shopware5 Sync abgeschlossen mit 1 Fehler"):
            call_command("shopware5_sync_products", "581000", stdout=StringIO())

        runtime.close.assert_called_once()


class OrderServiceMicrotechWritebackTest(SimpleTestCase):
    def test_update_microtech_order_id_merges_existing_custom_fields(self):
        service = OrderService.__new__(OrderService)
        service.get_by_id = MagicMock(
            return_value={
                "data": [
                    {
                        "id": "order-1",
                        "customFields": {"existing": "keep"},
                    }
                ]
            }
        )
        service.request_patch = MagicMock(return_value={"ok": True})

        result = service.update_microtech_order_id(order_id="order-1", erp_order_id="WB26/324")

        self.assertEqual(result, {"ok": True})
        service.request_patch.assert_called_once_with(
            "/order/order-1",
            payload={
                "customFields": {
                    "existing": "keep",
                    "microtech_beleg_nr": "WB26/324",
                    "microtech_erp_order_id": "WB26/324",
                }
            },
        )


class ProductMediaSyncServiceTest(SimpleTestCase):
    @patch.object(ProductService, "request_post")
    def test_get_sku_map_reads_product_number_from_top_level_response(self, mock_request_post):
        service = ProductService.__new__(ProductService)
        service.search_path = "/search/product"
        mock_request_post.return_value = {
            "data": [
                {
                    "id": "shopware-product-900001",
                    "productNumber": "900001",
                }
            ]
        }

        result = ProductService.get_sku_map(service, ["900001"])

        self.assertEqual(result, {"900001": "shopware-product-900001"})
        mock_request_post.assert_called_once_with(
            "/search/product",
            payload={
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "productNumber",
                        "value": "900001",
                    }
                ],
                "limit": 1,
            },
        )

    @patch.object(ProductService, "get_by_number")
    @patch.object(ProductService, "request_post")
    def test_get_sku_map_retries_missing_product_numbers_with_single_lookup(
        self,
        mock_request_post,
        mock_get_by_number,
    ):
        service = ProductService.__new__(ProductService)
        service.search_path = "/search/product"
        mock_request_post.return_value = {"data": []}
        mock_get_by_number.return_value = {
            "data": [
                {
                    "id": "shopware-product-900002",
                    "productNumber": "900002",
                }
            ]
        }

        result = ProductService.get_sku_map(service, ["900002"])

        self.assertEqual(result, {"900002": "shopware-product-900002"})
        mock_get_by_number.assert_called_once_with("900002", limit=1)

    @patch.object(ProductService, "request_post")
    def test_get_product_option_map_reads_flat_and_json_api_option_payloads(self, mock_request_post):
        mock_request_post.return_value = {
            "data": [
                {"id": "product-1", "optionIds": ["option-1", "option-2"]},
                {"id": "product-2", "options": [{"id": "option-3"}]},
                {"id": "product-3", "attributes": {"optionIds": ["option-4"]}},
                {
                    "id": "product-4",
                    "relationships": {"options": {"data": [{"id": "option-5"}]}},
                },
            ]
        }
        service = ProductService.__new__(ProductService)

        result = ProductService.get_product_option_map(
            service,
            ["product-4", "product-2", "product-1", "product-3"],
        )

        self.assertEqual(
            result,
            {
                "product-1": {"option-1", "option-2"},
                "product-2": {"option-3"},
                "product-3": {"option-4"},
                "product-4": {"option-5"},
            },
        )
        mock_request_post.assert_called_once_with(
            "/search/product",
            payload={
                "filter": [
                    {
                        "type": "equalsAny",
                        "field": "id",
                        "value": "product-1|product-2|product-3|product-4",
                    }
                ],
                "associations": {"options": {}},
                "limit": 4,
            },
        )

    @patch.object(ProductService, "request_post")
    def test_bulk_delete_product_options_uses_product_option_sync_delete(self, mock_request_post):
        service = ProductService.__new__(ProductService)

        ProductService.bulk_delete_product_options(
            service,
            [{"productId": "product-1", "optionId": "option-1"}],
        )

        mock_request_post.assert_called_once_with(
            "/_action/sync",
            payload={
                "product_option-delete": {
                    "entity": "product_option",
                    "action": "delete",
                    "payload": [{"productId": "product-1", "optionId": "option-1"}],
                }
            },
        )

    def test_split_file_name_extracts_base_name_and_extension(self):
        base_name, extension = ProductMediaSyncService.split_file_name("produkt-bild.JPEG")

        self.assertEqual(base_name, "produkt-bild")
        self.assertEqual(extension, "jpeg")

    @patch.object(ProductService, "request_post")
    def test_upload_media_from_url_uses_shopware_upload_endpoint(self, mock_request_post):
        service = ProductService.__new__(ProductService)
        service.delete_conflicting_media_by_filename = MagicMock(return_value=0)

        ProductService.upload_media_from_url(
            service,
            media_id="media-1",
            file_name="bild.png",
            source_url="https://cdn.example.com/img/bild.png",
        )

        mock_request_post.assert_called_once_with(
            "/_action/media/media-1/upload",
            payload={"url": "https://cdn.example.com/img/bild.png"},
            additional_query_params={"extension": "png", "fileName": "bild"},
        )

    @patch.object(ProductService, "request_post")
    def test_upload_media_from_url_retries_after_duplicate_filename_conflict(self, mock_request_post):
        service = ProductService.__new__(ProductService)
        service.delete_conflicting_media_by_filename = MagicMock(return_value=1)
        mock_request_post.side_effect = [
            RuntimeError("Shopware request failed (409): CONTENT__MEDIA_DUPLICATED_FILE_NAME"),
            {"ok": True},
        ]

        result = ProductService.upload_media_from_url(
            service,
            media_id="media-2",
            file_name="bild.jpg",
            source_url="https://cdn.example.com/img/bild.jpg",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(service.delete_conflicting_media_by_filename.call_count, 2)
        mock_request_post.assert_called_with(
            "/_action/media/media-2/upload",
            payload={"url": "https://cdn.example.com/img/bild.jpg"},
            additional_query_params={"extension": "jpg", "fileName": "bild"},
        )

    @patch.object(ProductService, "request_delete")
    @patch.object(ProductService, "request_post")
    def test_delete_conflicting_media_by_filename_removes_other_media_ids(self, mock_request_post, mock_request_delete):
        service = ProductService.__new__(ProductService)
        mock_request_post.return_value = {
            "data": [
                {"id": "media-1"},
                {"id": "media-2"},
            ]
        }

        deleted = ProductService.delete_conflicting_media_by_filename(
            service,
            file_name="bild",
            extension="jpg",
            exclude_media_id="media-1",
        )

        self.assertEqual(deleted, 1)
        mock_request_post.assert_called_once_with(
            "/search/media",
            payload={
                "filter": [
                    {"type": "equals", "field": "fileName", "value": "bild"},
                    {"type": "equals", "field": "fileExtension", "value": "jpg"},
                ],
                "limit": 50,
            },
        )
        mock_request_delete.assert_called_once_with("/media/media-2")


class ProductMediaSyncHashRegressionTest(TestCase):
    def test_hash_stays_stable_when_only_updated_at_changes(self):
        product = Product.objects.create(erp_nr="A-6001", sku="shopware-product-6001", name="Hash Stabil")
        image = Image.objects.create(path="stable-cover.jpg")
        product_image = ProductImage.objects.create(product=product, image=image, order=1)

        first_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        product_image.updated_at = timezone.now()
        product_image.save(update_fields=["updated_at"])
        product.refresh_from_db()
        second_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        self.assertEqual(first_hash, second_hash)

    def test_hash_changes_when_image_order_changes(self):
        product = Product.objects.create(erp_nr="A-6002", sku="shopware-product-6002", name="Hash Reihenfolge")
        first = Image.objects.create(path="first-cover.jpg")
        second = Image.objects.create(path="second-cover.jpg")
        first_relation = ProductImage.objects.create(product=product, image=first, order=1)
        second_relation = ProductImage.objects.create(product=product, image=second, order=2)

        first_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        first_relation.order = 2
        first_relation.save(update_fields=["order"])
        second_relation.order = 1
        second_relation.save(update_fields=["order"])
        product.refresh_from_db()
        second_hash = ProductMediaSyncService().build_media_sync_hash(product=product)

        self.assertNotEqual(first_hash, second_hash)

    def test_media_payload_follows_product_image_order(self):
        product = Product.objects.create(erp_nr="A-6003", sku="shopware-product-6003", name="Payload Reihenfolge")
        later = Image.objects.create(path="later.jpg")
        first = Image.objects.create(path="first.jpg")
        ProductImage.objects.create(product=product, image=later, order=2)
        ProductImage.objects.create(product=product, image=first, order=1)

        media_relations, media_entities, media_uploads = ProductMediaSyncService().get_product_media_payload(
            product=product,
            product_id="shopware-product-6003",
        )

        self.assertEqual([relation["position"] for relation in media_relations], [1, 2])
        self.assertEqual(
            [relation["productId"] for relation in media_relations],
            ["shopware-product-6003", "shopware-product-6003"],
        )
        self.assertEqual([upload["file_name"] for upload in media_uploads], ["first.jpg", "later.jpg"])
        self.assertEqual(len(media_entities), 2)

    def test_media_payload_contains_all_product_media_relations(self):
        product = Product.objects.create(erp_nr="A-6004", sku="shopware-product-6004", name="Mehrere Bilder")
        images = [
            Image.objects.create(path="front.jpg"),
            Image.objects.create(path="detail.jpg"),
            Image.objects.create(path="packaging.jpg"),
        ]
        for order, image in enumerate(images, start=1):
            ProductImage.objects.create(product=product, image=image, order=order)

        media_relations, _media_entities, _media_uploads = ProductMediaSyncService().get_product_media_payload(
            product=product,
            product_id="shopware-product-6004",
        )

        self.assertEqual(len(media_relations), 3)
        self.assertEqual(
            [relation["productId"] for relation in media_relations],
            ["shopware-product-6004"] * 3,
        )
        self.assertEqual([relation["position"] for relation in media_relations], [1, 2, 3])


class ShopwareSyncProductsCommandBatchTest(TestCase):
    @patch("shopware.management.commands.shopware_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware_sync_products.ProductService")
    def test_handle_separates_missing_sku_products_from_main_upsert_batch(
        self,
        product_service_factory,
        mock_runtime_start,
    ):
        runtime = MagicMock()
        mock_runtime_start.return_value = runtime

        service = MagicMock()
        service.get_sku_map.return_value = {}
        product_service_factory.return_value = service

        Product.objects.create(erp_nr="A-7001", sku="sku-1", name="Mit SKU")
        Product.objects.create(erp_nr="A-7002", name="Ohne SKU")

        cmd = ShopwareSyncProductsCommand()
        cmd.handle(erp_nrs=[], all=True, limit=2, batch_size=10, only_with_images=False, log_images=False)

        self.assertEqual(service.bulk_upsert.call_count, 2)
        main_payloads = service.bulk_upsert.call_args_list[0].args[0]
        fallback_payloads = service.bulk_upsert.call_args_list[1].args[0]

        self.assertEqual([payload["productNumber"] for payload in main_payloads], ["A-7001"])
        self.assertEqual(main_payloads[0]["id"], "sku-1")
        self.assertEqual([payload["productNumber"] for payload in fallback_payloads], ["A-7002"])
        self.assertNotIn("id", fallback_payloads[0])
        runtime.close.assert_called_once()

    @patch("shopware.management.commands.shopware_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware_sync_products.ProductService")
    def test_handle_replays_full_price_payload_after_fallback_sku_resolution(
        self,
        product_service_factory,
        mock_runtime_start,
    ):
        runtime = MagicMock()
        mock_runtime_start.return_value = runtime

        service = MagicMock()
        service.get_sku_map.side_effect = [{}, {"A-7004": "sku-4"}]
        product_service_factory.return_value = service

        default_channel = ShopwareSettings.objects.create(
            name="Default",
            is_active=True,
            is_default=True,
            currency_id="currency-default",
            rule_id_price="rule-default",
        )
        b2b_channel = ShopwareSettings.objects.create(
            name="B2B",
            is_active=True,
            currency_id="currency-b2b",
            rule_id_price="rule-b2b",
        )
        product = Product.objects.create(erp_nr="A-7004", name="Fallback Preisprodukt")
        Price.objects.create(product=product, sales_channel=default_channel, price=Decimal("10.00"))
        Price.objects.create(product=product, sales_channel=b2b_channel, price=Decimal("12.50"))

        cmd = ShopwareSyncProductsCommand()
        cmd.handle(erp_nrs=["A-7004"], all=False, limit=None, batch_size=10, only_with_images=False, log_images=False)

        self.assertEqual(service.bulk_upsert.call_count, 2)
        initial_fallback_payload = service.bulk_upsert.call_args_list[0].args[0][0]
        resolved_payload = service.bulk_upsert.call_args_list[1].args[0][0]

        self.assertNotIn("id", initial_fallback_payload)
        self.assertEqual(resolved_payload["id"], "sku-4")
        self.assertIn("price", resolved_payload)
        self.assertIn("prices", resolved_payload)
        self.assertEqual(
            [entry["ruleId"] for entry in resolved_payload["prices"]],
            ["rule-default", "rule-b2b"],
        )
        service.purge_product_prices_by_product_and_rule.assert_called_once_with(
            product_ids=["sku-4"],
            rule_ids=["rule-default", "rule-b2b"],
        )
        product.refresh_from_db()
        self.assertEqual(product.sku, "sku-4")
        runtime.close.assert_called_once()

    @patch("shopware.management.commands.shopware_sync_products.CommandRuntimeService.start")
    @patch("shopware.management.commands.shopware_sync_products.ProductService")
    def test_handle_uses_erp_number_as_name_fallback_when_product_name_is_blank(
        self,
        product_service_factory,
        mock_runtime_start,
    ):
        runtime = MagicMock()
        mock_runtime_start.return_value = runtime

        service = MagicMock()
        service.get_sku_map.return_value = {}
        product_service_factory.return_value = service

        Product.objects.create(erp_nr="A-7003", sku="sku-3", name=None, name_de=None, name_en=None)

        cmd = ShopwareSyncProductsCommand()
        cmd.handle(erp_nrs=["A-7003"], all=False, limit=None, batch_size=10, only_with_images=False, log_images=False)

        payloads = service.bulk_upsert.call_args.args[0]
        self.assertEqual(payloads[0]["name"], "A-7003")
        runtime.close.assert_called_once()


class ShopwareVariantSyncServiceTest(TestCase):
    def setUp(self):
        self.target_category = Category.objects.create(
            name="Quick-Tabs",
            slug="shopware-quick-tabs-parent",
            sw6_id="quick-tabs-category-id",
        )
        self.source_category = Category.objects.create(name="Quick-Tabs Quelle", slug="shopware-quick-tabs-source")
        self.size_group = PropertyGroup.objects.create(name="Tab-Größe", external_key="size")
        self.color_group = PropertyGroup.objects.create(name="Farbe", external_key="color")
        self.size = PropertyValue.objects.create(group=self.size_group, name="6 cm", external_key="6cm")
        self.color_image = Image.objects.create(path="quick-tabs-color-white.jpg")
        self.color = PropertyValue.objects.create(
            group=self.color_group,
            name="Weiß",
            external_key="white",
            image=self.color_image,
            position=20,
        )
        self.color_group.shopware_id = "color-group-id"
        self.color_group.save(update_fields=("shopware_id", "updated_at"))
        self.color.shopware_id = "color-option-id"
        self.color.save(update_fields=("shopware_id", "updated_at"))
        self.product = Product.objects.create(erp_nr="581000", name="Quick-Tabs 6 cm weiß")
        self.product.categories.add(self.source_category)
        self.image = Image.objects.create(path="quick-tabs-default.jpg")
        ProductImage.objects.create(product=self.product, image=self.image, order=1)
        ShopwareSettings.objects.create(
            name="Deutsch",
            sales_channel_id="sales-channel-de",
            is_active=True,
            is_default=True,
        )
        ShopwareSettings.objects.create(
            name="Inaktiver Verkaufskanal",
            sales_channel_id="sales-channel-inactive",
            is_active=False,
        )
        ProductProperty.objects.create(product=self.product, value=self.size)
        ProductProperty.objects.create(product=self.product, value=self.color)
        self.family = ProductVariantFamily.objects.create(
            slug="quick-tabs",
            name="Quick-Tabs",
            description="Parent für Quick-Tabs",
            shopware_product_number="PARENT-QUICK-TABS",
            target_category=self.target_category,
            default_product=self.product,
        )
        self.family.source_categories.add(self.source_category)
        ProductVariantAttribute.objects.create(family=self.family, property_group=self.size_group, position=10)
        ProductVariantAttribute.objects.create(
            family=self.family,
            property_group=self.color_group,
            position=20,
            display_type=ProductVariantAttribute.DisplayType.IMAGE,
        )

    def test_dry_run_derives_variant_without_calling_shopware(self):
        product_service = MagicMock()

        result = ShopwareVariantSyncService(product_service=product_service).sync(self.family, dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertEqual(result.variant_count, 1)
        product_service.method_calls.assert_not_called()

    def test_dry_run_rejects_image_display_without_selection_image(self):
        self.color.image = None
        self.color.save(update_fields=("image", "updated_at"))
        product_service = MagicMock()

        result = ShopwareVariantSyncService(product_service=product_service).sync(self.family, dry_run=True)

        self.assertEqual(result.errors, ("Bilddarstellung für 'Farbe' ohne Auswahlbild: Weiß.",))
        product_service.method_calls.assert_not_called()

    def test_apply_creates_parent_attaches_options_and_detaches_previously_managed_child(self):
        stale_product = Product.objects.create(erp_nr="291004W", name="Alte Quick-Tab-Variante")
        self.family.synced_products.add(stale_product)
        product_service = MagicMock()
        product_service.request_post.return_value = {"data": []}
        product_service.find_sku_by_number.return_value = "parent-shopware-id"
        product_service.get_sku_map.side_effect = lambda numbers: {
            number: {"581000": "child-shopware-id", "291004W": "stale-shopware-id"}[number]
            for number in numbers
        }

        result = ShopwareVariantSyncService(product_service=product_service).sync(self.family)

        self.assertFalse(result.dry_run)
        self.assertEqual(result.parent_id, "parent-shopware-id")
        self.assertEqual(result.variant_count, 1)
        self.assertEqual(result.detached_count, 1)
        self.assertEqual(
            list(self.family.synced_products.values_list("erp_nr", flat=True)),
            ["581000"],
        )

        product_payloads = [
            call.args[0]
            for call in product_service.bulk_upsert.call_args_list
            if call.kwargs.get("entity_name", "product") == "product"
        ]
        parent_payloads = [
            product
            for payload in product_payloads
            for product in payload
            if product.get("productNumber") == "PARENT-QUICK-TABS"
        ]
        self.assertEqual(len(parent_payloads), 2)
        self.assertTrue(all(payload["stock"] == 0 for payload in parent_payloads))
        self.assertTrue(all(payload["isCloseout"] is False for payload in parent_payloads))
        media_id = ProductMediaSyncService.build_media_id(self.image.path)
        expected_parent_media = [
            {
                "id": ProductMediaSyncService.build_product_media_id(
                    product_id="parent-shopware-id",
                    media_id=media_id,
                ),
                "productId": "parent-shopware-id",
                "mediaId": media_id,
                "position": 1,
            }
        ]
        self.assertTrue(all(payload["media"] == expected_parent_media for payload in parent_payloads))
        self.assertTrue(all(payload["coverId"] == expected_parent_media[0]["id"] for payload in parent_payloads))
        color_media_id = ProductMediaSyncService.build_media_id(self.color_image.path)
        product_service.bulk_upsert_media.assert_called_once_with(
            [ProductMediaSyncService.build_media_entity_payload(color_media_id)]
        )
        product_service.upload_media_from_url.assert_called_once_with(
            media_id=color_media_id,
            file_name="quick-tabs-color-white.jpg",
            source_url=self.color_image.url,
        )
        product_service.bulk_upsert.assert_any_call(
            [
                {
                    "id": "color-option-id",
                    "groupId": "color-group-id",
                    "name": "Weiß",
                    "mediaId": color_media_id,
                    "position": 20,
                }
            ],
            entity_name="property_group_option",
        )
        expected_size_option_id = ShopwareVariantSyncService._stable_id(
            "property-value",
            self.size_group.external_key,
            self.size.external_key,
        )
        product_service.bulk_upsert.assert_any_call(
            [
                {
                    "id": ShopwareVariantSyncService._stable_id(
                        "configurator-setting",
                        "parent-shopware-id",
                        expected_size_option_id,
                    ),
                    "productId": "parent-shopware-id",
                    "optionId": expected_size_option_id,
                    "position": self.size.position,
                },
                {
                    "id": ShopwareVariantSyncService._stable_id(
                        "configurator-setting",
                        "parent-shopware-id",
                        self.color.shopware_id,
                    ),
                    "productId": "parent-shopware-id",
                    "optionId": self.color.shopware_id,
                    "position": self.color.position,
                },
            ],
            entity_name="product_configurator_setting",
        )
        expected_visibilities = [
            {
                "id": ShopwareVariantSyncService._stable_id(
                    "product-visibility", "parent-shopware-id", "sales-channel-de"
                ),
                "salesChannelId": "sales-channel-de",
                "visibility": 30,
            }
        ]
        self.assertTrue(all(payload["visibilities"] == expected_visibilities for payload in parent_payloads))
        self.assertEqual(parent_payloads[0]["variantListingConfig"], {"displayParent": True})
        self.assertEqual(
            parent_payloads[1]["variantListingConfig"],
            {
                "displayParent": True,
                "mainVariantId": "child-shopware-id",
                "configuratorGroupConfig": [
                    {
                        "id": self.size_group.shopware_id,
                        "expressionForListings": False,
                        "position": 10,
                    },
                    {
                        "id": self.color_group.shopware_id,
                        "expressionForListings": False,
                        "position": 20,
                    },
                ],
            },
        )
        self.assertTrue(
            any(
                payload == [
                    {
                        "id": "child-shopware-id",
                        "productNumber": "581000",
                        "parentId": "parent-shopware-id",
                        "stock": 0,
                        "options": [
                            {"id": self.size.shopware_id},
                            {"id": self.color.shopware_id},
                        ],
                    }
                ]
                for payload in product_payloads
            )
        )
        self.assertIn(
            [
                {
                    "id": "stale-shopware-id",
                    "productNumber": "291004W",
                    "parentId": None,
                    "options": [],
                }
            ],
            product_payloads,
        )

    def test_apply_removes_stale_parent_configurator_settings(self):
        product_service = MagicMock()
        product_service.find_sku_by_number.return_value = "parent-shopware-id"
        product_service.get_sku_map.return_value = {"581000": "child-shopware-id"}
        expected_size_option_id = ShopwareVariantSyncService._stable_id(
            "property-value",
            self.size_group.external_key,
            self.size.external_key,
        )
        expected_setting_ids = {
            ShopwareVariantSyncService._stable_id(
                "configurator-setting",
                "parent-shopware-id",
                expected_size_option_id,
            ),
            ShopwareVariantSyncService._stable_id(
                "configurator-setting",
                "parent-shopware-id",
                self.color.shopware_id,
            ),
        }

        def request_post(path, payload):
            if path == "/search/product-configurator-setting":
                return {
                    "data": [
                        {"id": setting_id}
                        for setting_id in sorted({*expected_setting_ids, "stale-configurator-setting"})
                    ]
                }
            return {"data": []}

        product_service.request_post.side_effect = request_post

        ShopwareVariantSyncService(product_service=product_service).sync(self.family)

        product_service.request_delete.assert_called_once_with(
            "/product-configurator-setting/stale-configurator-setting"
        )

    def test_apply_removes_stale_child_options_before_upserting_children(self):
        product_service = MagicMock()
        product_service.request_post.return_value = {"data": []}
        product_service.find_sku_by_number.return_value = "parent-shopware-id"
        product_service.get_sku_map.return_value = {"581000": "child-shopware-id"}
        product_service.get_product_option_map.return_value = {
            "child-shopware-id": {"color-option-id", "obsolete-option-id"}
        }

        ShopwareVariantSyncService(product_service=product_service).sync(self.family)

        product_service.bulk_delete_product_options.assert_called_once_with(
            [{"productId": "child-shopware-id", "optionId": "obsolete-option-id"}]
        )
        delete_call_index = next(
            index
            for index, call in enumerate(product_service.mock_calls)
            if call[0] == "bulk_delete_product_options"
        )
        child_upsert_call_index = next(
            index
            for index, call in enumerate(product_service.mock_calls)
            if call[0] == "bulk_upsert"
            and call.args[0]
            and call.args[0][0].get("id") == "child-shopware-id"
        )
        self.assertLess(
            delete_call_index,
            child_upsert_call_index,
        )

    def test_apply_removes_all_child_options_before_detaching_stale_child(self):
        stale_product = Product.objects.create(erp_nr="291004W", name="Alte Quick-Tab-Variante")
        self.family.synced_products.add(stale_product)
        product_service = MagicMock()
        product_service.request_post.return_value = {"data": []}
        product_service.find_sku_by_number.return_value = "parent-shopware-id"
        product_service.get_sku_map.side_effect = lambda product_numbers: {
            product_number: {"581000": "child-shopware-id", "291004W": "stale-shopware-id"}[product_number]
            for product_number in product_numbers
        }
        product_service.get_product_option_map.return_value = {
            "stale-shopware-id": {"obsolete-size-option", "obsolete-color-option"}
        }

        ShopwareVariantSyncService(product_service=product_service).sync(self.family)

        product_service.bulk_delete_product_options.assert_called_once_with(
            [
                {"productId": "stale-shopware-id", "optionId": "obsolete-color-option"},
                {"productId": "stale-shopware-id", "optionId": "obsolete-size-option"},
            ]
        )

    def test_apply_cleans_parent_when_last_variant_attribute_is_deleted(self):
        stale_product = Product.objects.create(erp_nr="291004W", name="Alte Quick-Tab-Variante")
        self.family.synced_products.add(stale_product)
        self.family.variant_attributes.all().delete()
        product_service = MagicMock()
        product_service.find_sku_by_number.return_value = "parent-shopware-id"
        product_service.get_sku_map.return_value = {"291004W": "stale-shopware-id"}
        product_service.request_post.return_value = {"data": [{"id": "stale-configurator-setting"}]}

        result = ShopwareVariantSyncService(product_service=product_service).sync(self.family)

        self.assertEqual(result.variant_count, 0)
        self.assertEqual(result.detached_count, 1)
        self.assertFalse(self.family.synced_products.exists())
        product_service.request_delete.assert_called_once_with(
            "/product-configurator-setting/stale-configurator-setting"
        )
        product_service.bulk_upsert.assert_any_call(
            [
                {
                    "id": "stale-shopware-id",
                    "productNumber": "291004W",
                    "parentId": None,
                    "options": [],
                }
            ]
        )
        product_service.bulk_upsert.assert_any_call(
            [
                {
                    "id": "parent-shopware-id",
                    "variantListingConfig": {
                        "displayParent": True,
                        "configuratorGroupConfig": [],
                    },
                }
            ]
        )


class ForceProductImageUploadsCommandTest(TestCase):
    @patch("shopware.management.commands.shopware_force_product_image_uploads.ProductService")
    def test_handle_processes_all_products_when_no_erp_numbers_are_given(self, product_service_factory):
        service = MagicMock()
        service.get_sku_map.return_value = {}
        service.purge_product_media_by_product_ids.return_value = 2
        product_service_factory.return_value = service

        first = Product.objects.create(erp_nr="A-5001", sku="sku-5001", shopware_image_sync_hash="hash-1")
        second = Product.objects.create(
            erp_nr="A-5002",
            sku="sku-5002",
            shopware_image_sync_hash="hash-2",
            is_active=False,
        )
        first_image = Image.objects.create(path="first-force.jpg")
        second_image = Image.objects.create(path="second-force.jpg")
        ProductImage.objects.create(product=first, image=first_image, order=1)
        ProductImage.objects.create(product=second, image=second_image, order=1)

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=False, limit=None, batch_size=10, erp_nrs=[], only_with_images=False, log_images=False)

        service.purge_product_media_by_product_ids.assert_called_once()
        self.assertEqual(
            service.purge_product_media_by_product_ids.call_args.kwargs["product_ids"],
            ["sku-5001", "sku-5002"],
        )
        self.assertEqual(service.upload_media_from_url.call_count, 2)
        self.assertEqual(service.bulk_upsert.call_count, 1)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertNotEqual(first.shopware_image_sync_hash, "hash-1")
        self.assertNotEqual(second.shopware_image_sync_hash, "hash-2")

    @patch("shopware.management.commands.shopware_force_product_image_uploads.ProductService")
    def test_handle_processes_only_selected_erp_numbers(self, product_service_factory):
        service = MagicMock()
        service.get_sku_map.return_value = {}
        service.purge_product_media_by_product_ids.return_value = 1
        product_service_factory.return_value = service

        target = Product.objects.create(erp_nr="A-5003", sku="sku-5003", shopware_image_sync_hash="hash-3")
        untouched = Product.objects.create(erp_nr="A-5004", shopware_image_sync_hash="hash-4")
        image = Image.objects.create(path="selected-force.jpg")
        ProductImage.objects.create(product=target, image=image, order=1)

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=False, limit=None, batch_size=10, erp_nrs=["A-5003"], only_with_images=False, log_images=False)

        target.refresh_from_db()
        untouched.refresh_from_db()
        self.assertNotEqual(target.shopware_image_sync_hash, "hash-3")
        self.assertEqual(untouched.shopware_image_sync_hash, "hash-4")
        service.purge_product_media_by_product_ids.assert_called_once()
        self.assertEqual(
            service.purge_product_media_by_product_ids.call_args.kwargs["product_ids"],
            ["sku-5003"],
        )

    @patch("shopware.management.commands.shopware_force_product_image_uploads.ProductService")
    def test_handle_collects_batch_errors_and_skips_assignment_after_upload_failure(self, product_service_factory):
        service = MagicMock()
        service.get_sku_map.return_value = {}
        service.purge_product_media_by_product_ids.return_value = 1
        service.upload_media_from_url.side_effect = RuntimeError("upload failed")
        product_service_factory.return_value = service

        product = Product.objects.create(erp_nr="A-5005", sku="sku-5005", shopware_image_sync_hash="hash-5")
        image = Image.objects.create(path="broken-force.jpg")
        ProductImage.objects.create(product=product, image=image, order=1)

        cmd = ForceProductImageUploadsCommand()
        with self.assertRaises(CommandError):
            cmd.handle(all=False, limit=None, batch_size=10, erp_nrs=[], only_with_images=False, log_images=False)

        service.purge_product_media_by_product_ids.assert_called_once()
        service.upload_media_from_url.assert_called_once()
        service.bulk_upsert.assert_not_called()
        product.refresh_from_db()
        self.assertEqual(product.shopware_image_sync_hash, "hash-5")
