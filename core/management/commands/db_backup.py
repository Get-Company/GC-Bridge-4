from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "PostgreSQL-Datenbank sichern oder wiederherstellen.\n\n"
        "  backup  — erstellt einen pg_dump im Custom-Format (.dump)\n"
        "  restore — stellt ein Backup wieder her (erfordert --confirm)\n"
        "  list    — zeigt vorhandene Backups im Backup-Verzeichnis"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=["backup", "restore", "list"],
        )
        parser.add_argument(
            "--file",
            default="",
            metavar="PATH",
            help="Backup-Datei (bei restore: Pflicht; bei backup: optionaler Zielpfad).",
        )
        parser.add_argument(
            "--dir",
            default="",
            metavar="DIR",
            help="Backup-Verzeichnis (Standard: DB_BACKUP_DIR env oder tmp/backups/).",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=0,
            metavar="N",
            help="Nur die letzten N Backups behalten (0 = alle behalten).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Pflicht-Flag fuer restore, um versehentlichen Datenverlust zu verhindern.",
        )

    def handle(self, *args, **options):
        action = options["action"]
        if action == "backup":
            self._backup(options)
        elif action == "restore":
            self._restore(options)
        else:
            self._list(options)

    # ------------------------------------------------------------------ helpers

    def _db_params(self) -> dict[str, str]:
        db = settings.DATABASES["default"]
        return {
            "host": str(db.get("HOST") or "localhost"),
            "port": str(db.get("PORT") or "5432"),
            "user": str(db.get("USER") or ""),
            "password": str(db.get("PASSWORD") or ""),
            "name": str(db.get("NAME") or ""),
        }

    def _pg_env(self, password: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PGPASSWORD"] = password
        return env

    def _backup_dir(self, options) -> Path:
        raw = options["dir"] or os.getenv("DB_BACKUP_DIR", "tmp/backups")
        path = Path(raw)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _existing_dumps(self, backup_dir: Path) -> list[Path]:
        return sorted(backup_dir.glob("gc_bridge_*.dump"), key=lambda p: p.stat().st_mtime)

    # ------------------------------------------------------------------ actions

    def _backup(self, options):
        db = self._db_params()

        if options["file"]:
            output_path = Path(options["file"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self._backup_dir(options) / f"gc_bridge_{timestamp}.dump"

        cmd = [
            "pg_dump",
            "--format=custom",
            "--compress=6",
            f"--host={db['host']}",
            f"--port={db['port']}",
            f"--username={db['user']}",
            f"--dbname={db['name']}",
            f"--file={output_path}",
        ]

        self.stdout.write(f"Backup → {output_path} …")
        try:
            result = subprocess.run(cmd, env=self._pg_env(db["password"]), capture_output=True, text=True)
        except FileNotFoundError:
            raise CommandError(
                "pg_dump nicht gefunden. "
                "Stelle sicher, dass postgresql-client-16 im Container installiert ist."
            )

        if result.returncode != 0:
            raise CommandError(f"pg_dump fehlgeschlagen (exit {result.returncode}):\n{result.stderr.strip()}")

        size_mb = output_path.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Backup erstellt: {output_path} ({size_mb:.1f} MB)"))

        if options["keep"] > 0 and not options["file"]:
            self._prune(self._backup_dir(options), options["keep"])

    def _restore(self, options):
        if not options["confirm"]:
            raise CommandError(
                "Restore erfordert das Flag --confirm um versehentlichen Datenverlust zu verhindern.\n"
                "  python manage.py db_backup restore --file BACKUP.dump --confirm"
            )

        backup_file = options["file"]
        if not backup_file:
            raise CommandError("--file ist fuer restore erforderlich.")

        backup_path = Path(backup_file)
        if not backup_path.exists():
            raise CommandError(f"Backup-Datei nicht gefunden: {backup_path}")

        db = self._db_params()
        cmd = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            f"--host={db['host']}",
            f"--port={db['port']}",
            f"--username={db['user']}",
            f"--dbname={db['name']}",
            str(backup_path),
        ]

        self.stdout.write(self.style.WARNING(
            f"Restore von {backup_path.name} in Datenbank '{db['name']}' …"
        ))
        try:
            result = subprocess.run(cmd, env=self._pg_env(db["password"]), capture_output=True, text=True)
        except FileNotFoundError:
            raise CommandError(
                "pg_restore nicht gefunden. "
                "Stelle sicher, dass postgresql-client-16 im Container installiert ist."
            )

        # pg_restore exits with 1 on non-fatal warnings (e.g. DROP on non-existent objects).
        if result.returncode > 1:
            raise CommandError(f"pg_restore fehlgeschlagen (exit {result.returncode}):\n{result.stderr.strip()}")

        if result.stderr.strip():
            self.stderr.write(self.style.WARNING(f"Warnungen:\n{result.stderr.strip()}"))

        self.stdout.write(self.style.SUCCESS(f"Restore abgeschlossen: {backup_path.name}"))

    def _list(self, options):
        backup_dir = self._backup_dir(options)
        dumps = self._existing_dumps(backup_dir)
        if not dumps:
            self.stdout.write(f"Keine Backups in {backup_dir}")
            return
        self.stdout.write(f"Backups in {backup_dir}:")
        for dump in reversed(dumps):
            size_mb = dump.stat().st_size / 1024 / 1024
            mtime = datetime.fromtimestamp(dump.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            self.stdout.write(f"  {dump.name}  {size_mb:6.1f} MB  {mtime}")

    def _prune(self, backup_dir: Path, keep: int):
        dumps = self._existing_dumps(backup_dir)
        for old in dumps[:-keep]:
            old.unlink()
            self.stdout.write(f"Altes Backup geloescht: {old.name}")
