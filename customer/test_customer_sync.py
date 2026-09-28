from __future__ import annotations

from django.test import SimpleTestCase

from customer.services.customer_sync import CustomerSyncService


class _FakeContactDataset:
    def __init__(self, records):
        self.records = records
        self.cursor = 0
        self.range = None

    def set_range(self, from_range, to_range):
        self.range = (from_range, to_range)
        self.cursor = 0
        return True

    def range_eof(self):
        return self.cursor >= len(self.records)

    def get_field(self, field_name):
        return self.records[self.cursor].get(field_name)

    def range_next(self):
        self.cursor += 1


class CustomerSyncContactBatchTest(SimpleTestCase):
    def test_contacts_are_loaded_once_for_the_whole_customer_and_grouped_by_address(self):
        dataset = _FakeContactDataset(
            [
                {"ID": 11, "AnsNr": 4, "AspNr": 1, "VNa": "Ada", "NNa": "Lovelace"},
                {"ID": 12, "AnsNr": 4, "AspNr": 2, "VNa": "Grace", "NNa": "Hopper"},
                {"ID": 13, "AnsNr": 9, "AspNr": 1, "VNa": "Edsger", "NNa": "Dijkstra"},
            ]
        )

        grouped = CustomerSyncService()._load_contacts_by_address(
            ansprechpartner_service=dataset,
            customer_erp_nr="36415",
        )

        self.assertEqual(dataset.range, (["36415", 0, 0], ["36415", 999, 999_999]))
        self.assertEqual([contact["asp_nr"] for contact in grouped[4]], [1, 2])
        self.assertEqual(grouped[9][0]["last_name"], "Dijkstra")
