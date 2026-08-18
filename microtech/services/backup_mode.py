"""Wartungszustand fuer das microtech-Backup-Fenster.

Waehrend ein Backup laeuft, ist die COM-Verbindung zu microtech geschlossen.
Ohne Gegenmassnahme wuerden Celery-Beat-Laeufe und Admin-Aktionen weiter Jobs
einreihen, die alle scheitern. Dieses Modul haelt den Zustand lokal fest und
weist neue Microtech-Arbeit fuer die Dauer des Fensters mit einer klaren
Meldung ab.

Bewusst ohne Nachhol-Mechanismus: abgewiesene Laeufe werden nicht gepuffert,
die naechsten regulaeren Laeufe holen den Stand ohnehin nach.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.formats import date_format

from core.services import BaseService
from microtech.models import MicrotechSettings
from microtech.services.graphql_client import MicrotechBackupModeActive

# Diese Operationen muessen das Gate immer passieren duerfen - sonst kaeme man
# aus einem offenen Backup-Fenster nicht mehr heraus.
BACKUP_MODE_EXEMPT_OPERATIONS = frozenset(
    {
        "enterMicrotechBackupMode",
        "leaveMicrotechBackupMode",
        "microtechBackupMode",
        "stopMicrotechWorker",
        "startMicrotechWorker",
        "microtechWorkerStatus",
    }
)


def _parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed


class MicrotechBackupModeService(BaseService):
    """Liest und schreibt den lokalen Zustand des Backup-Fensters."""

    @staticmethod
    def load() -> MicrotechSettings:
        return MicrotechSettings.load()

    @classmethod
    def is_active(cls) -> bool:
        return bool(cls.load().backup_mode_active)

    @classmethod
    def ensure_available(cls, *, operation: str = "") -> None:
        """Bricht mit MicrotechBackupModeActive ab, wenn ein Fenster offen ist."""
        if operation and operation in BACKUP_MODE_EXEMPT_OPERATIONS:
            return

        config = cls.load()
        if not config.backup_mode_active:
            return

        raise MicrotechBackupModeActive(cls.rejection_message(config))

    @staticmethod
    def rejection_message(config: MicrotechSettings | None = None) -> str:
        config = config or MicrotechSettings.load()
        since = (
            date_format(timezone.localtime(config.backup_mode_entered_at), "SHORT_DATETIME_FORMAT")
            if config.backup_mode_entered_at
            else "unbekannt"
        )
        until = (
            date_format(timezone.localtime(config.backup_mode_deadline), "SHORT_DATETIME_FORMAT")
            if config.backup_mode_deadline
            else "unbekannt"
        )
        return (
            f"Microtech-Backup-Fenster aktiv seit {since}, voraussichtlich frei ab {until}. "
            "Die Verbindung zu microtech ist bis dahin geschlossen."
        )

    @classmethod
    def mark_entered(cls, *, deadline_at: str | None = None, requested_by: str = "") -> MicrotechSettings:
        """Fenster lokal als offen vermerken - nur nach bestaetigtem Wrapper-Erfolg."""
        config = cls.load()
        now = timezone.now()
        deadline = _parse_deadline(deadline_at)
        if deadline is None:
            deadline = now + timedelta(minutes=int(settings.MICROTECH_BACKUP_MODE_DEADLINE_MINUTES))

        config.backup_mode_active = True
        config.backup_mode_entered_at = now
        config.backup_mode_deadline = deadline
        config.backup_mode_started_by = str(requested_by or "")[:150]
        config.save(
            update_fields=(
                "backup_mode_active",
                "backup_mode_entered_at",
                "backup_mode_deadline",
                "backup_mode_started_by",
            )
        )
        return config

    @classmethod
    def mark_left(cls) -> MicrotechSettings:
        """Fenster lokal schliessen - nur nach bestaetigtem Wiederanlauf."""
        config = cls.load()
        config.backup_mode_active = False
        config.backup_mode_entered_at = None
        config.backup_mode_deadline = None
        config.backup_mode_started_by = ""
        config.save(
            update_fields=(
                "backup_mode_active",
                "backup_mode_entered_at",
                "backup_mode_deadline",
                "backup_mode_started_by",
            )
        )
        return config

    @classmethod
    def is_deadline_exceeded(cls, *, now: datetime | None = None) -> bool:
        config = cls.load()
        if not config.backup_mode_active or config.backup_mode_deadline is None:
            return False
        return (now or timezone.now()) > config.backup_mode_deadline
