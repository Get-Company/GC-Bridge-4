from django.test import TestCase

from microtech.models import MicrotechOrderRuleDjangoField
from microtech.rule_builder import sync_django_field_catalog
from orders.models import Order


class FieldCatalogExampleTest(TestCase):
    def check_snapshot_example(self):
        snapshot = {"price": {"details": "ö" * 600}}
        order = Order.objects.create(api_id="catalog-long-example", shopware_price_snapshot=snapshot)
        sync_django_field_catalog()
        example = MicrotechOrderRuleDjangoField.objects.get(field_path="shopware_price_snapshot")
        limit = MicrotechOrderRuleDjangoField._meta.get_field("example").max_length
        self.assertEqual(example.example, str(snapshot)[:limit])
        example.full_clean()
        order.refresh_from_db()
        self.assertEqual(order.shopware_price_snapshot, snapshot)

    def test_new_catalog_entry_limits_long_price_snapshot_example(self):
        MicrotechOrderRuleDjangoField.objects.filter(field_path="shopware_price_snapshot").delete()
        self.check_snapshot_example()

    def test_existing_catalog_entry_limits_long_price_snapshot_example(self):
        MicrotechOrderRuleDjangoField.objects.update_or_create(
            field_path="shopware_price_snapshot",
            defaults={"label": "Previous label", "value_kind": "string", "example": "old"},
        )
        self.check_snapshot_example()
