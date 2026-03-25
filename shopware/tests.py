from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from products.models import Product
from shopware.management.commands.shopware_force_product_image_uploads import Command as ForceProductImageUploadsCommand
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


class ForceProductImageUploadsCommandTest(TestCase):
    @patch("shopware.management.commands.shopware_force_product_image_uploads.call_command")
    def test_handle_resets_hashes_and_runs_shopware_sync_for_all(self, mock_call_command):
        Product.objects.create(erp_nr="A-5001", shopware_image_sync_hash="hash-1")
        Product.objects.create(erp_nr="A-5002", shopware_image_sync_hash="hash-2")

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=True, limit=25, batch_size=10, erp_nrs=[])

        self.assertEqual(Product.objects.exclude(shopware_image_sync_hash="").count(), 0)
        mock_call_command.assert_called_once_with(
            "shopware_sync_products",
            all=True,
            limit=25,
            batch_size=10,
        )

    @patch("shopware.management.commands.shopware_force_product_image_uploads.call_command")
    def test_handle_resets_selected_hashes_and_runs_shopware_sync_for_selection(self, mock_call_command):
        target = Product.objects.create(erp_nr="A-5003", shopware_image_sync_hash="hash-3")
        untouched = Product.objects.create(erp_nr="A-5004", shopware_image_sync_hash="hash-4")

        cmd = ForceProductImageUploadsCommand()
        cmd.handle(all=False, limit=None, batch_size=50, erp_nrs=["A-5003"])

        target.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(target.shopware_image_sync_hash, "")
        self.assertEqual(untouched.shopware_image_sync_hash, "hash-4")
        mock_call_command.assert_called_once_with(
            "shopware_sync_products",
            "A-5003",
            limit=None,
            batch_size=50,
        )

    def test_handle_requires_selection_or_all(self):
        cmd = ForceProductImageUploadsCommand()

        with self.assertRaises(CommandError):
            cmd.handle(all=False, limit=None, batch_size=50, erp_nrs=[])
