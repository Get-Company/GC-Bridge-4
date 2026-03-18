from django.test import TestCase

from microtech.models import MicrotechSwissCustomsFieldMapping


class MicrotechSwissCustomsFieldMappingTest(TestCase):
    def test_defaults_are_seeded_with_adapted_project_sources(self):
        self.assertTrue(MicrotechSwissCustomsFieldMapping.objects.exists())

        customer_reference = MicrotechSwissCustomsFieldMapping.objects.get(portal_field="customerReference")
        self.assertEqual(customer_reference.source_type, MicrotechSwissCustomsFieldMapping.SourceType.CUSTOMER)
        self.assertEqual(customer_reference.source_path, "erp_nr")

        importer_tax_id = MicrotechSwissCustomsFieldMapping.objects.get(portal_field="importer.taxId")
        self.assertEqual(importer_tax_id.source_type, MicrotechSwissCustomsFieldMapping.SourceType.CUSTOMER)
        self.assertEqual(importer_tax_id.source_path, "vat_id")

        line_item_commodity = MicrotechSwissCustomsFieldMapping.objects.get(portal_field="lineItem.commodityCode")
        self.assertEqual(line_item_commodity.source_type, MicrotechSwissCustomsFieldMapping.SourceType.PRODUCT)
        self.assertEqual(line_item_commodity.source_path, "customs_tariff_number")

    def test_ensure_defaults_does_not_override_existing_admin_changes(self):
        mapping = MicrotechSwissCustomsFieldMapping.objects.get(portal_field="parcelNumbers")
        mapping.static_value = "MANUAL-OVERRIDE"
        mapping.save(update_fields=["static_value", "updated_at"])

        MicrotechSwissCustomsFieldMapping.ensure_defaults()

        mapping.refresh_from_db()
        self.assertEqual(mapping.static_value, "MANUAL-OVERRIDE")
