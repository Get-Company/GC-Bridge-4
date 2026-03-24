from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService
from shopware.services.shopware6 import InvalidTokenError, Shopware6Service


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


class ProductMediaSyncServiceTest(SimpleTestCase):
    def test_split_file_name_extracts_base_name_and_extension(self):
        base_name, extension = ProductMediaSyncService.split_file_name("produkt-bild.JPEG")

        self.assertEqual(base_name, "produkt-bild")
        self.assertEqual(extension, "jpeg")

    @patch.object(ProductService, "request_post")
    def test_upload_media_from_url_uses_shopware_upload_endpoint(self, mock_request_post):
        service = ProductService.__new__(ProductService)

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
