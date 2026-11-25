from unittest.mock import patch

from django.test import SimpleTestCase

from customer.models import Customer
from microtech.services.graphql_client import GraphQLMicrotechError, MicrotechGraphQLClientService
from orders.models import Order
from orders.services.order_upsert_microtech import OrderUpsertMicrotechService


class CustomsVorgangLookupTest(SimpleTestCase):
    def setUp(self):
        self.order = Order(
            api_id="shopware-order-10387",
            order_number="10387",
            erp_order_id="WB26/1335",
            customer=Customer(erp_nr="13747"),
        )
        self.client = object.__new__(MicrotechGraphQLClientService)

    def test_download_lookup_prefers_current_document_by_order_number(self):
        result = {
            "records": [{
                "BelegNr": "26/1792",
                "AuftrNr": "10387",
                "AdrNr": "13747",
                "Bez": "Shopware Bestellung 10387",
            }],
        }
        with (
            patch.object(self.client, "poll_dataset_records", return_value=result) as dataset_read,
            patch.object(self.client, "request_vorgang") as old_beleg_read,
            patch.object(OrderUpsertMicrotechService, "_persist_erp_order_id") as persist,
            patch.object(OrderUpsertMicrotechService, "_persist_erp_vorgang_id"),
        ):
            beleg_nr = OrderUpsertMicrotechService().refresh_erp_order_id(self.order, erp=self.client)

        self.assertEqual(beleg_nr, "26/1792")
        self.assertEqual(dataset_read.call_args.args[0]["filter"], "AuftrNr = '10387'")
        old_beleg_read.assert_not_called()
        persist.assert_called_once_with(order=self.order, erp_order_id="26/1792")

    def test_missing_old_document_still_falls_back_to_order_number(self):
        result = {
            "vorgaenge": [{"BelegNr": "26/1792", "AuftrNr": "10387", "AdrNr": "13747"}],
        }
        with (
            patch.object(
                self.client, "request_vorgang",
                side_effect=GraphQLMicrotechError("Es wurde kein Vorgang mit der Belegnummer gefunden."),
            ),
            patch.object(self.client, "poll_dataset_records", return_value=result),
            patch.object(OrderUpsertMicrotechService, "_clear_erp_order_id"),
            patch.object(OrderUpsertMicrotechService, "_persist_erp_order_id"),
            patch.object(OrderUpsertMicrotechService, "_persist_erp_vorgang_id"),
        ):
            beleg_nr = OrderUpsertMicrotechService()._refresh_erp_order_id_graphql(
                order=self.order, client=self.client,
            )

        self.assertEqual(beleg_nr, "26/1792")

    def test_ambiguous_order_number_does_not_choose_an_arbitrary_document(self):
        result = {
            "records": [
                {"BelegNr": "26/1792", "AuftrNr": "10387", "AdrNr": "13747"},
                {"BelegNr": "26/1800", "AuftrNr": "10387", "AdrNr": "13747"},
            ],
        }
        with patch.object(self.client, "poll_dataset_records", return_value=result):
            with self.assertRaisesRegex(ValueError, "eindeutige Zuordnung"):
                OrderUpsertMicrotechService().refresh_erp_order_id(self.order, erp=self.client)
