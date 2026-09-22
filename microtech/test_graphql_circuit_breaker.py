from __future__ import annotations

from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings

from microtech.models import MicrotechSettings
from microtech.services.graphql_circuit_breaker import GraphQLMicrotechCircuitOpen
from microtech.services.graphql_client import MicrotechGraphQLClientService, MicrotechGraphQLConfig


@override_settings(MICROTECH_GRAPHQL_CIRCUIT_FAILURE_THRESHOLD=2, MICROTECH_GRAPHQL_CIRCUIT_RESET_SECONDS=300)
class GraphQLCircuitBreakerTest(TestCase):
    def setUp(self):
        self.client = MicrotechGraphQLClientService(
            config=MicrotechGraphQLConfig(url="http://wrapper.invalid/graphql/"),
        )

    @patch("microtech.services.graphql_client.requests.post", side_effect=requests.exceptions.ConnectionError("offline"))
    def test_opens_after_repeated_transport_errors_and_prevents_a_third_request(self, mock_post):
        with self.assertRaises(requests.exceptions.ConnectionError):
            self.client.execute("query { version }")
        with self.assertRaises(requests.exceptions.ConnectionError):
            self.client.execute("query { version }")

        config = MicrotechSettings.load()
        self.assertEqual(config.graphql_consecutive_failures, 2)
        self.assertIsNotNone(config.graphql_circuit_open_until)

        with self.assertRaises(GraphQLMicrotechCircuitOpen):
            self.client.execute("query { version }")
        self.assertEqual(mock_post.call_count, 2)

    @patch("microtech.services.graphql_client.requests.post")
    def test_sends_the_stable_idempotency_key_with_mutations(self, mock_post):
        response = Mock()
        response.json.return_value = {"data": {"ok": True}}
        mock_post.return_value = response
        client = MicrotechGraphQLClientService(
            config=MicrotechGraphQLConfig(url="http://wrapper.invalid/graphql/"),
            idempotency_key="gc-bridge-graphql-job-42",
        )

        self.assertEqual(client.execute("mutation { example }")["ok"], True)

        self.assertEqual(mock_post.call_args.kwargs["headers"]["X-Idempotency-Key"], "gc-bridge-graphql-job-42")
