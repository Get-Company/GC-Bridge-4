from unittest.mock import patch

from django.test import SimpleTestCase

from microtech.services.graphql_client import MicrotechGraphQLClientService


class SubmitMutationTest(SimpleTestCase):
    def _accepted(self):
        return {"accepted": True, "jobId": "job-123", "retryAfterSeconds": 42}

    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_submit_update_customer_returns_job_id_without_polling(self, mock_mutation):
        mock_mutation.return_value = self._accepted()
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        job_id, retry_after = client.submit_update_customer("100012", {"city": "Kassel"})

        self.assertEqual(job_id, "job-123")
        self.assertEqual(retry_after, 42.0)
        mock_mutation.assert_called_once()
        # field-Argument der Mutation ist updateCustomer
        self.assertEqual(mock_mutation.call_args.args[1], "updateCustomer")

    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_submit_create_postal_address_uses_create_field(self, mock_mutation):
        mock_mutation.return_value = self._accepted()
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        job_id, _ = client.submit_create_postal_address(100012, {"city": "Kassel"})

        self.assertEqual(job_id, "job-123")
        self.assertEqual(mock_mutation.call_args.args[1], "createPostalAddress")

    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_submit_upsert_customer_uses_upsert_field(self, mock_mutation):
        mock_mutation.return_value = self._accepted()
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        job_id, _ = client.submit_upsert_customer("100012", {"city": "Kassel"})

        self.assertEqual(job_id, "job-123")
        self.assertEqual(mock_mutation.call_args.args[1], "upsertCustomer")

    @patch.object(MicrotechGraphQLClientService, "poll_job")
    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_microtech_connection_uses_connection_mutation(self, mock_execute, mock_poll):
        mock_execute.return_value = {"microtechConnection": self._accepted()}
        mock_poll.return_value = {"result": {"mandant": "58"}}
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.microtech_connection(timeout=5)

        self.assertEqual(result, {"mandant": "58"})
        self.assertIn("microtechConnection", mock_execute.call_args.args[0])
        self.assertEqual(mock_poll.call_args.kwargs["timeout"], 5)

    @patch.object(MicrotechGraphQLClientService, "poll_job")
    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_switch_microtech_mandant_uses_switch_field(self, mock_mutation, mock_poll):
        mock_mutation.return_value = self._accepted()
        mock_poll.return_value = {"result": {"mandant": "59"}}
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.switch_microtech_mandant("59", timeout=5)

        self.assertEqual(result, {"mandant": "59"})
        self.assertEqual(mock_mutation.call_args.args[1], "switchMicrotechMandant")
        self.assertEqual(mock_mutation.call_args.args[2], {"mandant": "59"})
        self.assertEqual(mock_poll.call_args.kwargs["timeout"], 5)
