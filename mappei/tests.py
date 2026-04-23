from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from products.models import Image, Product, ProductImage

from .models import MappeiProduct


class MappeiProductMappingAutocompleteTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        self.client.force_login(self.user)

    def test_visual_autocomplete_includes_mappei_product_image_url(self):
        MappeiProduct.objects.create(
            artikelnr="M-RED",
            name="Register rot",
            image_url="https://example.test/mappei-red.jpg",
        )

        response = self.client.get(
            reverse("admin:mappei_mappeiproductmapping_visual_autocomplete"),
            {
                "app_label": "mappei",
                "model_name": "mappeiproductmapping",
                "field_name": "mappei_product",
                "term": "red",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"][0]["image_url"],
            "https://example.test/mappei-red.jpg",
        )

    def test_visual_autocomplete_includes_internal_product_image_url(self):
        product = Product.objects.create(erp_nr="P-RED", name="Register rot")
        image = Image.objects.create(path="products/red.jpg", alt_text="Rot")
        ProductImage.objects.create(product=product, image=image, order=1)

        response = self.client.get(
            reverse("admin:mappei_mappeiproductmapping_visual_autocomplete"),
            {
                "app_label": "mappei",
                "model_name": "mappeiproductmapping",
                "field_name": "product",
                "term": "P-RED",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["image_url"], image.url)
