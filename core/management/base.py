from __future__ import annotations

from django.core.management.base import BaseCommand

from issues.services import TaskIssueCollector


class MonitoredBaseCommand(BaseCommand):
    """BaseCommand der alle ERROR+ Loguru-Meldungen automatisch als Issue sammelt."""

    def execute(self, *args, **options):
        task_name = type(self).__module__.split(".")[-1]
        with TaskIssueCollector(task_name):
            return super().execute(*args, **options)
