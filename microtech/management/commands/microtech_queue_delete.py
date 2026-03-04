from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from microtech.services import MicrotechQueueService


class Command(BaseCommand):
    help = "Deletes selected jobs from the Microtech queue."

    def add_arguments(self, parser):
        parser.add_argument(
            "job_ids",
            nargs="+",
            type=int,
            help="One or more MicrotechJob IDs to delete.",
        )
        parser.add_argument(
            "--include-running",
            action="store_true",
            help="Also allow deletion of currently RUNNING jobs.",
        )

    def handle(self, *args, **options):
        job_ids = list(options.get("job_ids") or [])
        include_running = bool(options.get("include_running"))

        result = MicrotechQueueService().delete_jobs(
            job_ids=job_ids,
            include_running=include_running,
        )

        requested_ids = result["requested_ids"]
        existing_ids = result["existing_ids"]
        deleted_ids = result["deleted_ids"]
        protected_running_ids = result["protected_running_ids"]
        missing_ids = [job_id for job_id in requested_ids if job_id not in existing_ids]

        self.stdout.write(f"Angefragt: {', '.join(str(job_id) for job_id in requested_ids)}")
        if deleted_ids:
            self.stdout.write(self.style.SUCCESS(f"Geloescht: {', '.join(str(job_id) for job_id in deleted_ids)}"))
        else:
            self.stdout.write("Geloescht: -")

        if protected_running_ids:
            self.stdout.write(
                self.style.WARNING(
                    "RUNNING (geschuetzt): " + ", ".join(str(job_id) for job_id in protected_running_ids)
                )
            )
        if missing_ids:
            self.stdout.write(self.style.WARNING("Nicht gefunden: " + ", ".join(str(job_id) for job_id in missing_ids)))

        if not deleted_ids and not protected_running_ids and missing_ids:
            raise CommandError("Keine der angefragten Job-IDs existiert.")
