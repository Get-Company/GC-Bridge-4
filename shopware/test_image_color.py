from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from PIL import Image, ImageCms

from shopware.services.image_color import ImageColorProfileService
from shopware.services.product import ProductService
from shopware.services.shopware6 import Shopware6Service


class ImageColorProfileTest(SimpleTestCase):
    def _image_bytes(self, *, mode="RGB", color="white", profile=None, format="PNG"):
        image = Image.new(mode, (8, 8), color)
        output = BytesIO()
        image.save(output, format=format, **({"icc_profile": profile} if profile else {}))
        return output.getvalue()

    def test_converts_lab_profile_to_srgb_with_correct_white(self):
        lab_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
        content = self._image_bytes(mode="LAB", color=(255, 128, 128), profile=lab_profile.tobytes(), format="TIFF")
        result = ImageColorProfileService().normalize(content)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertTrue(all(channel >= 254 for channel in image.getpixel((0, 0))))
            profile = ImageCms.ImageCmsProfile(BytesIO(image.info["icc_profile"]))
            self.assertIn("sRGB", ImageCms.getProfileDescription(profile))

    def test_preserves_png_transparency(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        content = self._image_bytes(mode="RGBA", color=(255, 255, 255, 63), profile=profile)
        with Image.open(BytesIO(ImageColorProfileService().normalize(content))) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255, 63))

    def test_untagged_rgb_keeps_original_bytes_without_jpeg_recompression(self):
        content = self._image_bytes(format="JPEG")
        self.assertEqual(ImageColorProfileService().normalize(content), content)

    def test_invalid_profile_fails_before_upload(self):
        content = self._image_bytes(profile=b"invalid ICC profile")
        with self.assertRaises((OSError, ImageCms.PyCMSError)):
            ImageColorProfileService().normalize(content)

    @patch("shopware.services.image_color.requests.get")
    def test_download_is_bounded_and_cached(self, get):
        content = self._image_bytes()
        response = get.return_value.__enter__.return_value
        response.iter_content.return_value = [content]
        service = ImageColorProfileService()
        self.assertEqual(service.prepare_upload(source_url="https://assets.example/image.png"), content)
        self.assertEqual(service.prepare_upload(source_url="https://assets.example/image.png"), content)
        get.assert_called_once()
        service.max_download_bytes = 1
        with self.assertRaisesRegex(ValueError, "Download-Limit"):
            service.prepare_upload(source_url="https://assets.example/other.png")

    def test_preparation_failure_does_not_delete_existing_media(self):
        service = ProductService.__new__(ProductService)
        service.prepare_media_upload = MagicMock(side_effect=ValueError("bad profile"))
        service.delete_conflicting_media_by_filename = MagicMock()
        with self.assertRaisesRegex(ValueError, "bad profile"):
            service.upload_media_from_url(media_id="media-id", file_name="image.jpg", source_url="https://assets.example/image.jpg")
        service.delete_conflicting_media_by_filename.assert_not_called()


class BinaryMediaUploadTest(SimpleTestCase):
    def _service(self, client):
        service = Shopware6Service.__new__(Shopware6Service)
        service.client = client
        client.config = SimpleNamespace(follow_redirects=True)
        client._format_admin_api_url.return_value = "https://shop.example/api/_action/media/id/upload"
        return service

    def test_sends_raw_bytes_without_stringifying_them(self):
        client = MagicMock()
        response = client.session.post.return_value
        response.status_code = 204
        response.is_error = False
        response.content = b""
        service = self._service(client)
        content = b"\xff\xd8\x00\x01"
        self.assertEqual(service.request_binary("/_action/media/id/upload", content=content, additional_query_params={"extension":"jpg"}), {})
        self.assertEqual(client.session.post.call_args.kwargs["content"], content)

    def test_refreshes_client_once_after_unauthorized_response(self):
        first, second = MagicMock(), MagicMock()
        self._service(second)
        first.session.post.return_value.status_code = 401
        second.session.post.return_value.status_code = 204
        second.session.post.return_value.is_error = False
        second.session.post.return_value.content = b""
        service = self._service(first)
        service._build_client = MagicMock(return_value=second)
        self.assertEqual(service.request_binary("/upload", content=b"image", additional_query_params={}), {})
        service._build_client.assert_called_once()
        second.session.post.assert_called_once()
