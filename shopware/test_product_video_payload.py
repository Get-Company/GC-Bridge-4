from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from products.models import Image, Product, ProductVideo, Video
from products.services import disable_product_auto_sync
from shopware.management.commands.shopware_sync_products import (
    _build_product_videos,
    _build_product_sync_payload,
    _prefetch_sync_queryset,
    _public_https_url,
)


class ProductVideoPayloadUnitTest(SimpleTestCase):
    def test_serializer_uses_the_plugin_contract_and_omits_inactive_assignments(self):
        first = SimpleNamespace(
            is_active=True,
            position=10,
            video=SimpleNamespace(
                is_active=True,
                vimeo_id="111111",
                privacy_hash="abc123",
                title="Zuerst",
                poster=SimpleNamespace(url="https://assets.classei.de/poster.jpg"),
            ),
        )
        inactive = SimpleNamespace(
            is_active=False,
            position=20,
            video=SimpleNamespace(
                is_active=True,
                vimeo_id="222222",
                privacy_hash="",
                title="Inaktiv",
                poster=None,
            ),
        )
        product = SimpleNamespace(
            prefetched_product_videos_for_shopware_sync=[first, inactive],
        )

        self.assertEqual(
            _build_product_videos(product),
            [
                {
                    "provider": "vimeo",
                    "videoId": "111111",
                    "privacyHash": "abc123",
                    "title": "Zuerst",
                    "position": 10,
                    "posterUrl": "https://assets.classei.de/poster.jpg",
                }
            ],
        )

    def test_poster_url_filter_rejects_internal_and_non_https_urls(self):
        self.assertEqual(
            _public_https_url("https://assets.classei.de/poster.jpg"),
            "https://assets.classei.de/poster.jpg",
        )
        self.assertEqual(_public_https_url("http://assets.classei.de/poster.jpg"), "")
        self.assertEqual(_public_https_url("https://10.0.0.165/poster.jpg"), "")
        self.assertEqual(_public_https_url("/relative/poster.jpg"), "")


@override_settings(MICROTECH_IMAGE_BASE_URL="https://assets.classei.example/img/")
class ProductVideoPayloadTest(TestCase):
    def _payload(self, product):
        return _build_product_sync_payload(
            product=product,
            effective_sku="",
            default_channel=None,
            channels=[],
            admin_user_id=None,
            content_type_id=None,
        )

    def test_payload_serializes_active_videos_in_position_order(self):
        with disable_product_auto_sync():
            product = Product.objects.create(erp_nr="PAYLOAD-1", name="Videos", factor=5)
            poster = Image.objects.create(path="poster.jpg")
            later = Video.objects.create(title="Später", vimeo_id="222222")
            first = Video.objects.create(
                title="Zuerst",
                vimeo_id="111111",
                privacy_hash="abc123",
                poster=poster,
            )
            inactive = Video.objects.create(title="Inaktiv", vimeo_id="333333", is_active=False)
            ProductVideo.objects.create(product=product, video=later, position=20)
            ProductVideo.objects.create(product=product, video=first, position=10)
            ProductVideo.objects.create(product=product, video=inactive, position=5)

        prefetched_product = _prefetch_sync_queryset(Product.objects.filter(pk=product.pk)).get()
        payload = self._payload(prefetched_product)

        self.assertEqual(
            payload["customFields"],
            {
                "geco_product_videos": [
                    {
                        "provider": "vimeo",
                        "videoId": "111111",
                        "privacyHash": "abc123",
                        "title": "Zuerst",
                        "position": 10,
                        "posterUrl": "https://assets.classei.example/img/poster.jpg",
                    },
                    {
                        "provider": "vimeo",
                        "videoId": "222222",
                        "title": "Später",
                        "position": 20,
                    },
                ],
                "geco_price_factor_value": 5,
            },
        )

    @override_settings(MICROTECH_IMAGE_BASE_URL="http://10.0.0.165/img/")
    def test_payload_never_exposes_internal_or_non_https_poster_urls(self):
        with disable_product_auto_sync():
            product = Product.objects.create(erp_nr="PAYLOAD-2", name="Internes Poster")
            poster = Image.objects.create(path="poster.jpg")
            video = Video.objects.create(title="Video", vimeo_id="444444", poster=poster)
            ProductVideo.objects.create(product=product, video=video)

        payload = self._payload(product)

        self.assertEqual(
            payload["customFields"]["geco_product_videos"],
            [{"provider": "vimeo", "videoId": "444444", "title": "Video", "position": 100}],
        )

    def test_payload_always_sends_empty_list_to_clear_shopware(self):
        with disable_product_auto_sync():
            product = Product.objects.create(erp_nr="PAYLOAD-3", name="Ohne Video")

        payload = self._payload(product)

        self.assertEqual(payload["customFields"], {"geco_product_videos": []})
