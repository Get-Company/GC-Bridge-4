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
        parser.add_argument(
            "--all-statuses",
            action="store_true",
            help="Include terminal jobs (succeeded/failed/cancelled) as well.",
        )
        parser.add_argument(
            "--status",
            action="append",
            choices=[choice for choice, _ in MicrotechJob.Status.choices],
            help="Filter jobs by status (can be specified multiple times).",
        )
        parser.add_argument(
            "--job-type",
            action="append",
            choices=[choice for choice, _ in MicrotechJob.JobType.choices],
            help="Filter jobs by job type (can be specified multiple times).",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))
        limit = max(1, int(options.get("limit") or 20))
        all_statuses = bool(options.get("all_statuses"))
        status_filters = list(options.get("status") or [])
        job_type_filters = list(options.get("job_type") or [])

        summary = MicrotechQueueService().summarize()
        queryset = MicrotechJob.objects.all()
        if status_filters:
            queryset = queryset.filter(status__in=status_filters)
        elif not all_statuses:
            queryset = queryset.filter(
                status__in=[MicrotechJob.Status.QUEUED, MicrotechJob.Status.RUNNING]
            )
        if job_type_filters:
            queryset = queryset.filter(job_type__in=job_type_filters)

        jobs = list(
            queryset.order_by("priority", "run_after", "created_at", "id").values(
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
            "jobs": jobs,
            "filters": {
                "all_statuses": all_statuses,
                "status": status_filters,
                "job_type": job_type_filters,
            },
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
        self.stdout.write(f"Jobs (limit {limit})")
        for item in jobs:
            self.stdout.write(
                f"- #{item['id']} {item['job_type']} [{item['status']}] "
                f"attempt={item['attempt']}/{item['max_retries'] + 1}"
            )
