from __future__ import annotations

from django.core.management.base import BaseCommand

from hr.services.setup_service import HrSetupService


class Command(BaseCommand):
    help = "Legt die HR-Gruppen mit den benoetigten Django-Model-Permissions idempotent an."

    def handle(self, *args, **options):
        groups = HrSetupService.ensure_groups()
        self.stdout.write(self.style.SUCCESS(f"HR-Gruppen eingerichtet: {', '.join(groups.keys())}"))
