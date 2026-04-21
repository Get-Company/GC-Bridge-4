"""Mappei daily price scheduler.

Runs as a daemon thread inside the Django server process.
Triggers scrape_mappei at 20:00 every day.
"""
from __future__ import annotations

import threading
from datetime import datetime

from django.utils import timezone
from loguru import logger


class MappeiSchedulerWorker:
    """Singleton daemon thread that triggers the Mappei scraper at 20:00 daily."""

    _instance: MappeiSchedulerWorker | None = None
    _lock = threading.Lock()

    # Hour (local server time) at which the scraper runs
    TRIGGER_HOUR = 20

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_run_date: datetime.date | None = None  # type: ignore[type-arg]

    @classmethod
    def get(cls) -> MappeiSchedulerWorker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="mappei-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Mappei scheduler worker started (trigger hour={}).", self.TRIGGER_HOUR)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("Mappei scheduler worker stopped.")

    def _run(self) -> None:
        """Main loop: check every minute whether it's time to run."""
        while not self._stop_event.is_set():
            now = timezone.localtime()
            if now.hour == self.TRIGGER_HOUR and self._last_run_date != now.date():
                self._last_run_date = now.date()
                self._trigger_scrape()
            # Sleep 60 s between checks; wake early on stop
            self._stop_event.wait(timeout=60)

    def _trigger_scrape(self) -> None:
        logger.info("Mappei scheduler: triggering daily price scrape.")
        try:
            from django.core.management import call_command
            call_command("scrape_mappei")
        except Exception:
            logger.exception("Mappei scheduler: scrape failed.")
