from unittest.mock import patch

from django.test import SimpleTestCase


class CleanupOldGraphQLJobsTaskTests(SimpleTestCase):
    @patch("microtech.services.MicrotechJobSentinelService.cleanup_old_jobs")
    def test_forwards_scheduler_parameters_to_sentinel(self, mock_cleanup):
        from microtech.tasks import cleanup_old_graphql_jobs

        mock_cleanup.return_value = {"deleted": 3, "failed": 1}

        result = cleanup_old_graphql_jobs.run(
            max_age_days=14,
            limit=25,
            terminal_only=False,
        )

        self.assertEqual(result, {"deleted": 3, "failed": 1})
        mock_cleanup.assert_called_once_with(
            max_age_days=14,
            limit=25,
            terminal_only=False,
        )
