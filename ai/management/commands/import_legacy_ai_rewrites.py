from __future__ import annotations

from core.management.base import MonitoredBaseCommand


class Command(MonitoredBaseCommand):
    help = "Veraltet: Der Legacy-AI-Rewrite-Import entfaellt nach dem Redesign."

    def handle(self, *args, **options):
        self.stdout.write(
            "Dieser Import ist nach dem AI-Rewriter-Redesign nicht mehr verfuegbar."
        )
