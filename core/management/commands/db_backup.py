from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django.core.management.base import CommandError
from core.management.base import MonitoredBaseCommand
from core.services import DatabaseBackupError, DatabaseBackupService


class Command(MonitoredBaseCommand):
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
            "--table",
            action="append",
            default=[],
            metavar="TABLE",
            help="Nur diese Tabelle sichern bzw. wiederherstellen. Mehrfach angeben.",
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

    # ------------------------------------------------------------------ actions

    def _backup(self, options):
        service = DatabaseBackupService()
        table_names = service.validate_table_names(options["table"])

        if options["file"]:
            output_path = Path(options["file"])
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self._backup_dir(options) / f"gc_bridge_{timestamp}.dump"

        self.stdout.write(f"Backup → {output_path} …")
        try:
            service.create_dump(output_path, table_names)
        except DatabaseBackupError as exc:
            raise CommandError(str(exc)) from exc

        size_mb = output_path.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Backup erstellt: {output_path} ({size_mb:.1f} MB)"))

        if options["keep"] > 0 and not options["file"]:
            for old in service.prune_backup_files(options["keep"], directory=output_path.parent):
                self.stdout.write(f"Altes Backup geloescht: {old.name}")

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

        service = DatabaseBackupService()
        try:
            table_names = service.validate_table_names(options["table"])
        except DatabaseBackupError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.WARNING(f"Restore von {backup_path.name} …"))
        try:
            service.restore_dump(backup_path, table_names)
        except DatabaseBackupError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Restore abgeschlossen: {backup_path.name}"))

    def _list(self, options):
        backup_dir = self._backup_dir(options)
        dumps = DatabaseBackupService().list_backup_files(directory=backup_dir)
        if not dumps:
            self.stdout.write(f"Keine Backups in {backup_dir}")
            return
        self.stdout.write(f"Backups in {backup_dir}:")
        for dump in reversed(dumps):
            size_mb = dump.stat().st_size / 1024 / 1024
            mtime = datetime.fromtimestamp(dump.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            self.stdout.write(f"  {dump.name}  {size_mb:6.1f} MB  {mtime}")

    def _backup_dir(self, options) -> Path:
        return DatabaseBackupService().backup_directory(options["dir"] or None)
