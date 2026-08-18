from unittest.mock import patch

from django.test import SimpleTestCase

from microtech.services.graphql_client import GraphQLMicrotechError, MicrotechGraphQLClientService


class SubmitMutationTest(SimpleTestCase):
    def _accepted(self):
        return {"accepted": True, "jobId": "job-123", "retryAfterSeconds": 42}

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

    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_submit_search_customers_uses_structured_customer_input(self, mock_mutation):
        mock_mutation.return_value = self._accepted()
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        job_id, retry_after = client.submit_search_customers(
            customer_number="100012",
            email="max@example.com",
            first_name="Max",
            last_name="Mustermann",
            limit=20,
        )

        self.assertEqual((job_id, retry_after), ("job-123", 42.0))
        self.assertEqual(mock_mutation.call_args.args[1], "searchCustomers")
        self.assertEqual(
            mock_mutation.call_args.args[2],
            {
                "input": {
                    "adrNr": "100012",
                    "email": "max@example.com",
                    "firstName": "Max",
                    "lastName": "Mustermann",
                    "limit": 20,
                }
            },
        )

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_customer_search_job_uses_dedicated_query(self, mock_execute):
        mock_execute.return_value = {"customerSearchJob": {"status": "DONE", "customers": []}}
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.customer_search_job("job-123")

        self.assertEqual(result["status"], "DONE")
        self.assertIn("customerSearchJob", mock_execute.call_args.args[0])
        self.assertEqual(mock_execute.call_args.args[1], {"jobId": "job-123"})

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

    # Wartungsoperationen laufen im API-Prozess des Wrappers und antworten
    # synchron - anders als die Job-Mutationen, die der COM-Worker abarbeitet.

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_stop_microtech_worker_returns_the_result_synchronously(self, mock_execute):
        mock_execute.return_value = {
            "stopMicrotechWorker": {
                "success": True,
                "message": "Worker beendet.",
                "errorMessage": None,
                "worker": {"running": False, "microtechConnected": False},
            }
        }
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.stop_microtech_worker()

        self.assertTrue(result["success"])
        self.assertFalse(result["worker"]["microtechConnected"])
        self.assertIn("stopMicrotechWorker", mock_execute.call_args.args[0])
        self.assertTrue(mock_execute.call_args.kwargs["bypass_backup_mode"])

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_start_microtech_worker_returns_the_result_synchronously(self, mock_execute):
        mock_execute.return_value = {
            "startMicrotechWorker": {
                "success": True,
                "message": "Worker gestartet.",
                "errorMessage": None,
                "worker": {"running": True, "microtechConnected": True},
            }
        }
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.start_microtech_worker()

        self.assertTrue(result["worker"]["microtechConnected"])
        self.assertIn("startMicrotechWorker", mock_execute.call_args.args[0])

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_maintenance_failure_raises_with_the_wrapper_message(self, mock_execute):
        mock_execute.return_value = {
            "stopMicrotechWorker": {
                "success": False,
                "message": "Worker konnte nicht stop werden.",
                "errorMessage": "Task manager timed out.",
                "worker": None,
            }
        }
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        with self.assertRaises(GraphQLMicrotechError) as caught:
            client.stop_microtech_worker()

        self.assertIn("Task manager timed out.", str(caught.exception))

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_enter_backup_mode_passes_deadline_and_requester(self, mock_execute):
        mock_execute.return_value = {
            "enterMicrotechBackupMode": {
                "success": True,
                "ready": True,
                "message": "Backup-Fenster geoeffnet.",
                "errorMessage": None,
                "deadlineAt": "2026-08-18T14:00:00+00:00",
                "services": [],
                "worker": None,
            }
        }
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.enter_microtech_backup_mode(deadline_minutes=45, requested_by="7")

        self.assertTrue(result["ready"])
        self.assertEqual(
            mock_execute.call_args.args[1],
            {"deadlineMinutes": 45, "requestedBy": "7"},
        )

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_backup_mode_query_reports_state_even_when_not_ready(self, mock_execute):
        mock_execute.return_value = {
            "microtechBackupMode": {
                "success": True,
                "ready": False,
                "active": True,
                "message": "Backup-Fenster ist aktiv.",
                "errorMessage": None,
                "services": [],
                "worker": None,
            }
        }
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        result = client.microtech_backup_mode()

        self.assertTrue(result["active"])
        self.assertFalse(result["ready"])

    @patch.object(MicrotechGraphQLClientService, "execute")
    def test_worker_status_uses_status_query(self, mock_execute):
        mock_execute.return_value = {
            "microtechWorkerStatus": {
                "success": True,
                "worker": self._worker(running=True, connected=True),
            }
        }

        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)
        result = client.microtech_worker_status()

        self.assertTrue(result["worker"]["microtechConnected"])
        self.assertIn("microtechWorkerStatus", mock_execute.call_args.args[0])
