from django.contrib import admin
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse

from products.models import Image, Product, ProductImage

from .models import MappeiProduct, MappeiProductMapping


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

    def test_mapping_widget_is_only_initialized_by_custom_autocomplete(self):
        model_admin = admin.site._registry[MappeiProductMapping]
        request = RequestFactory().get("/admin/mappei/mappeiproductmapping/add/")
        request.user = self.user
        form = model_admin.get_form(request)
        widget = form.base_fields["mappei_product"].widget.widget

        attrs = widget.build_attrs(widget.attrs)

        self.assertIn("mappei-product-mapping-autocomplete", attrs["class"])
        self.assertNotIn("admin-autocomplete", attrs["class"].split())

    def test_mapping_list_displays_mappei_and_internal_product_thumbnails(self):
        mappei_product = MappeiProduct.objects.create(
            artikelnr="M-BLUE",
            name="Register blau",
            image_url="https://example.test/mappei-blue.jpg",
        )
        product = Product.objects.create(erp_nr="P-BLUE", name="Register blau")
        image = Image.objects.create(path="products/blue.jpg", alt_text="Blau")
        ProductImage.objects.create(product=product, image=image, order=1)
        mapping = MappeiProductMapping.objects.create(
            mappei_product=mappei_product,
            product=product,
        )
        model_admin = admin.site._registry[MappeiProductMapping]

        self.assertIn(
            'src="https://example.test/mappei-blue.jpg"',
            str(model_admin.mappei_product_image_display(mapping)),
        )
        self.assertIn(
            f'src="{image.url}"',
            str(model_admin.product_image_display(mapping)),
        )

    def test_mapping_list_queryset_prefetches_product_images(self):
        mappei_product = MappeiProduct.objects.create(artikelnr="M-GREEN", name="Register gruen")
        product = Product.objects.create(erp_nr="P-GREEN", name="Register gruen")
        image = Image.objects.create(path="products/green.jpg", alt_text="Gruen")
        ProductImage.objects.create(product=product, image=image, order=1)
        mapping = MappeiProductMapping.objects.create(
            mappei_product=mappei_product,
            product=product,
        )
        model_admin = admin.site._registry[MappeiProductMapping]
        request = RequestFactory().get("/admin/mappei/mappeiproductmapping/")
        request.user = self.user

        loaded_mapping = model_admin.get_queryset(request).get(pk=mapping.pk)

        self.assertEqual(loaded_mapping.mappei_product.artikelnr, "M-GREEN")
        self.assertEqual(loaded_mapping.product.first_image, image)

    def test_mapping_combination_is_unique_but_allows_many_to_many_pairs(self):
        mappei_product = MappeiProduct.objects.create(artikelnr="M-M2M", name="Mappei M2M")
        second_mappei_product = MappeiProduct.objects.create(artikelnr="M-M2M-2", name="Mappei M2M 2")
        product = Product.objects.create(erp_nr="P-M2M", name="Classei M2M")
        second_product = Product.objects.create(erp_nr="P-M2M-2", name="Classei M2M 2")

        MappeiProductMapping.objects.create(mappei_product=mappei_product, product=product)
        MappeiProductMapping.objects.create(mappei_product=mappei_product, product=second_product)
        MappeiProductMapping.objects.create(mappei_product=second_mappei_product, product=product)

        self.assertEqual(mappei_product.products.count(), 2)
        self.assertEqual(product.mappei_products.count(), 2)

        with self.assertRaises(IntegrityError), transaction.atomic():
            MappeiProductMapping.objects.create(mappei_product=mappei_product, product=product)
