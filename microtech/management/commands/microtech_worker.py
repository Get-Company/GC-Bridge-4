from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from core.services import CommandRuntimeService
from microtech.services.worker import MicrotechWorkerService


class Command(BaseCommand):
    help = "Runs the dedicated Microtech queue worker (single COM connection)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--idle-sleep",
            type=float,
            default=2.0,
            help="Sleep in seconds when queue is empty.",
        )

    def handle(self, *args, **options):
        idle_sleep = float(options.get("idle_sleep") or 2.0)

        existing = [
            item
            for item in CommandRuntimeService().list_runs(include_stale=False, cleanup_stale=True)
            if item.get("command_name") == "microtech_worker"
        ]
        if existing:
            raise CommandError("microtech_worker is already running.")

        runtime = CommandRuntimeService().start(
            command_name="microtech_worker",
            argv=sys.argv,
            metadata={"idle_sleep_seconds": idle_sleep},
        )
        try:
            MicrotechWorkerService().run_forever(
                idle_sleep_seconds=idle_sleep,
                runtime_handle=runtime,
            )
        finally:
            runtime.close()
