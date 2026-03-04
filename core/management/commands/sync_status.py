from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand

from core.services import CommandRuntimeService


def _format_duration(seconds: int) -> str:
    return str(timedelta(seconds=max(0, int(seconds))))


class Command(BaseCommand):
    help = "Zeigt laufende Sync-/Scheduler-Commands und optional stale Eintraege."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Neben laufenden Jobs auch stale Eintraege anzeigen.",
        )
        parser.add_argument(
            "--cleanup-stale",
            action="store_true",
            help="Stale Eintraege aus tmp/runtime entfernen.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Ausgabe als JSON.",
        )

    def handle(self, *args, **options):
        include_stale = options.get("all", False)
        cleanup_stale = options.get("cleanup_stale", False)
        as_json = options.get("json", False)

        service = CommandRuntimeService()
        entries = service.list_runs(include_stale=include_stale, cleanup_stale=cleanup_stale)

        if as_json:
            self.stdout.write(json.dumps(entries, ensure_ascii=True, indent=2, sort_keys=True))
            return

        if not entries:
            self.stdout.write("Keine laufenden Sync-/Scheduler-Commands gefunden.")
            return

        self.stdout.write(f"Aktive Eintraege: {len(entries)}")
        for entry in entries:
            metadata = entry.get("metadata", {}) or {}
            stage = metadata.get("stage") or "-"
            line = (
                f"- [{entry.get('status', 'running')}] "
                f"{entry.get('command_name', '')} "
                f"(pid={entry.get('pid')}, host={entry.get('hostname')}, "
                f"laufzeit={_format_duration(int(entry.get('age_seconds') or 0))}, stage={stage})"
            )
            self.stdout.write(line)
