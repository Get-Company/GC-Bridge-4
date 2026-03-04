from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from microtech.models import MicrotechJob
from microtech.services import MicrotechQueueService


class Command(BaseCommand):
    help = "Shows Microtech queue statistics and optionally recent jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output as JSON.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="How many recent jobs to include.",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))
        limit = max(1, int(options.get("limit") or 20))

        summary = MicrotechQueueService().summarize()
        recent_jobs = list(
            MicrotechJob.objects.order_by("-created_at").values(
                "id",
                "job_type",
                "status",
                "attempt",
                "max_retries",
                "priority",
                "run_after",
                "started_at",
                "finished_at",
                "last_error",
            )[:limit]
        )

        payload = {
            "summary": summary,
            "recent_jobs": recent_jobs,
        }
        if as_json:
            self.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
            return

        counts = summary.get("counts", {})
        self.stdout.write("Microtech Queue")
        self.stdout.write(f"- queued: {counts.get(MicrotechJob.Status.QUEUED, 0)}")
        self.stdout.write(f"- running: {counts.get(MicrotechJob.Status.RUNNING, 0)}")
        self.stdout.write(f"- succeeded: {counts.get(MicrotechJob.Status.SUCCEEDED, 0)}")
        self.stdout.write(f"- failed: {counts.get(MicrotechJob.Status.FAILED, 0)}")
        self.stdout.write(f"- oldest_queued_at: {summary.get('oldest_queued_at') or '-'}")
        self.stdout.write("")
        self.stdout.write(f"Recent jobs (last {limit})")
        for item in recent_jobs:
            self.stdout.write(
                f"- #{item['id']} {item['job_type']} [{item['status']}] "
                f"attempt={item['attempt']}/{item['max_retries'] + 1}"
            )
