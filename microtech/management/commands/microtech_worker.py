from __future__ import annotations

import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from loguru import logger

from core.services import CommandRuntimeService
from microtech.models import MicrotechJob
from microtech.services.worker import MicrotechWorkerService

_LOG_PATH = settings.BASE_DIR / "tmp" / "logs" / "microtech_worker.log"


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

        # Always log to a file – the worker runs as a Windows Scheduled Task
        # under SYSTEM where stdout/stderr vanish.
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        sink_id = logger.add(
            str(_LOG_PATH),
            level="DEBUG",
            rotation="5 MB",
            retention="14 days",
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
        )

        try:
            self._run(idle_sleep)
        finally:
            logger.remove(sink_id)

    def _run(self, idle_sleep: float) -> None:
        existing = [
            item
            for item in CommandRuntimeService().list_runs(include_stale=False, cleanup_stale=True)
            if item.get("command_name") == "microtech_worker"
        ]
        if existing:
            logger.warning("microtech_worker is already running (PID {}).", existing[0].get("pid"))
            raise CommandError("microtech_worker is already running.")

        # Reset any jobs stuck in RUNNING from a previous crashed worker.
        stuck_qs = MicrotechJob.objects.filter(status=MicrotechJob.Status.RUNNING)
        stuck_count = stuck_qs.count()
        if stuck_count:
            stuck_qs.update(
                status=MicrotechJob.Status.QUEUED,
                run_after=timezone.now(),
                last_error="Reset: worker restarted",
                started_at=None,
                worker_id="",
            )
            logger.warning("Reset {} stuck RUNNING job(s) to QUEUED on worker startup.", stuck_count)

        logger.info("Starting microtech_worker (idle_sleep={}s).", idle_sleep)
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
        except Exception:
            logger.exception("microtech_worker exited with an unhandled error.")
            raise
        finally:
            logger.info("microtech_worker shutting down.")
            runtime.close()
