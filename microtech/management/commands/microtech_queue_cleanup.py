from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from microtech.models import MicrotechJob


class Command(BaseCommand):
    help = "Delete old succeeded/failed/cancelled Microtech queue jobs (default: >24h)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Delete jobs older than N hours (default: 24)")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["hours"])
        qs = MicrotechJob.objects.filter(
            status__in=[MicrotechJob.Status.SUCCEEDED, MicrotechJob.Status.FAILED, MicrotechJob.Status.CANCELLED],
            created_at__lt=cutoff,
        )
        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} old Microtech queue jobs (older than {options['hours']}h)."))
