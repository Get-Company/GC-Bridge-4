from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from microtech.services.graphql_client import GraphQLMicrotechError, MicrotechGraphQLClientService


class SubmitMutationTest(SimpleTestCase):
    def _accepted(self):
        return {"accepted": True, "jobId": "job-123", "retryAfterSeconds": 42}

    @staticmethod
    def _maintenance_client():
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)
        client.config = SimpleNamespace(maintenance_token="maintenance-token", poll_timeout=30.0, poll_interval=0.1)
        return client

    @staticmethod
    def _worker(*, running: bool, connected: bool) -> dict:
        return {
            "running": running,
            "microtechConnected": connected,
            "microtechUser": "api-benutzer",
            "connectionMessage": "status",
        }

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

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_stop_microtech_worker_uses_maintenance_token_and_requires_closed_com(self, mock_execute):
        mock_execute.return_value = {
            "stopMicrotechWorker": {
                "success": True,
                "message": "stopped",
                "worker": self._worker(running=False, connected=False),
            }
        }

        result = self._maintenance_client().stop_microtech_worker()

        self.assertFalse(result["worker"]["running"])
        self.assertIn("stopMicrotechWorker", mock_execute.call_args.args[0])
        self.assertEqual(
            mock_execute.call_args.kwargs["headers"],
            {"X-Microtech-Maintenance-Token": "maintenance-token"},
        )

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_stop_microtech_worker_rejects_an_active_worker(self, mock_execute):
        mock_execute.return_value = {
            "stopMicrotechWorker": {
                "success": True,
                "message": "stop requested",
                "worker": self._worker(running=True, connected=True),
            }
        }

        with self.assertRaises(GraphQLMicrotechError):
            self._maintenance_client().stop_microtech_worker()

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_worker_status_uses_status_query_and_maintenance_token(self, mock_execute):
        mock_execute.return_value = {
            "microtechWorkerStatus": {
                "success": True,
                "worker": self._worker(running=True, connected=True),
            }
        }

        result = self._maintenance_client().microtech_worker_status()

        self.assertTrue(result["worker"]["microtechConnected"])
        self.assertIn("microtechWorkerStatus", mock_execute.call_args.args[0])
        self.assertEqual(
            mock_execute.call_args.kwargs["headers"],
            {"X-Microtech-Maintenance-Token": "maintenance-token"},
        )

    @patch("microtech.services.graphql_client.time.sleep")
    @patch.object(MicrotechGraphQLClientService, "microtech_worker_status")
    def test_wait_for_microtech_worker_connection_polls_until_connected(self, mock_status, _mock_sleep):
        mock_status.side_effect = [
            {"success": True, "worker": self._worker(running=True, connected=False)},
            {"success": True, "worker": self._worker(running=True, connected=True)},
        ]

        result = self._maintenance_client().wait_for_microtech_worker_connection(timeout=5)

        self.assertTrue(result["worker"]["microtechConnected"])
        self.assertEqual(mock_status.call_count, 2)
