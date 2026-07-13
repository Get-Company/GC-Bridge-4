from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.db import connections
from django.utils import timezone

from core.models import DatabaseBackup

from .base import BaseService


class DatabaseBackupError(RuntimeError):
    pass


class DatabaseBackupService(BaseService):
    model = DatabaseBackup

    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
    backup_file_prefix = "gc_bridge_"

    def backup_directory(self, directory: str | Path | None = None) -> Path:
        configured = str(
            directory
            if directory is not None
            else getattr(settings, "DB_BACKUP_DIR", "tmp/backups") or "tmp/backups"
        ).strip()
        directory = Path(configured)
        if not directory.is_absolute():
            directory = Path(settings.BASE_DIR) / directory
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def schema_name(self) -> str:
        schema_name = str(getattr(settings, "DB_BACKUP_SCHEMA", "public") or "public").strip()
        if not self._IDENTIFIER_RE.fullmatch(schema_name):
            raise DatabaseBackupError("DB_BACKUP_SCHEMA muss ein gueltiger PostgreSQL-Schemaname sein.")
        return schema_name

    def list_database_tables(self) -> list[str]:
        connection = connections["default"]
        if connection.vendor != "postgresql":
            raise DatabaseBackupError("Datenbank-Backups werden nur fuer PostgreSQL unterstuetzt.")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = %s
                ORDER BY tablename
                """,
                [self.schema_name()],
            )
            return [str(row[0]) for row in cursor.fetchall() if self._IDENTIFIER_RE.fullmatch(str(row[0]))]

    def validate_table_names(self, table_names: Iterable[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in table_names or []:
            table_name = str(value or "").strip()
            if not table_name:
                continue
            if not self._IDENTIFIER_RE.fullmatch(table_name):
                raise DatabaseBackupError(f"Ungueltiger Tabellenname: {table_name}")
            if table_name not in seen:
                seen.add(table_name)
                normalized.append(table_name)
        return normalized

    def create_backup_request(
        self,
        *,
        table_names: Iterable[str] | None = None,
        label: str = "",
        requested_by=None,
    ) -> DatabaseBackup:
        return self.create(
            label=(label or "").strip(),
            table_names=self.validate_table_names(table_names),
            requested_by=requested_by,
        )

    def backup_path(self, backup: DatabaseBackup) -> Path:
        if not backup.file_name:
            raise DatabaseBackupError("Das Backup hat noch keine Sicherungsdatei.")
        if Path(backup.file_name).name != backup.file_name:
            raise DatabaseBackupError("Der gespeicherte Backup-Dateiname ist ungueltig.")
        return self.backup_directory() / backup.file_name

    def build_backup_path(self, backup: DatabaseBackup) -> Path:
        timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        return self.backup_directory() / f"{self.backup_file_prefix}{timestamp}_{backup.pk}.dump"

    def _database_options(self) -> dict[str, str]:
        database = settings.DATABASES["default"]
        return {
            "host": str(database.get("HOST") or "localhost"),
            "port": str(database.get("PORT") or "5432"),
            "user": str(database.get("USER") or ""),
            "password": str(database.get("PASSWORD") or ""),
            "name": str(database.get("NAME") or ""),
        }

    def _postgres_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PGPASSWORD"] = self._database_options()["password"]
        return environment

    def _qualified_tables(self, table_names: Iterable[str] | None) -> list[str]:
        schema_name = self.schema_name()
        return [f"{schema_name}.{table_name}" for table_name in self.validate_table_names(table_names)]

    def build_dump_command(self, output_path: Path, table_names: Iterable[str] | None = None) -> list[str]:
        database = self._database_options()
        command = [
            "pg_dump",
            "--format=custom",
            "--compress=6",
            f"--host={database['host']}",
            f"--port={database['port']}",
            f"--username={database['user']}",
            f"--dbname={database['name']}",
            f"--file={output_path}",
        ]
        command.extend(f"--table={table_name}" for table_name in self._qualified_tables(table_names))
        return command

    def build_restore_command(self, backup_path: Path, table_names: Iterable[str] | None = None) -> list[str]:
        database = self._database_options()
        command = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--host={database['host']}",
            f"--port={database['port']}",
            f"--username={database['user']}",
            f"--dbname={database['name']}",
        ]
        command.extend(f"--table={table_name}" for table_name in self._qualified_tables(table_names))
        command.append(str(backup_path))
        return command

    def _run_command(self, command: list[str], *, include_password: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                env=self._postgres_environment() if include_password else None,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DatabaseBackupError(
                f"{command[0]} wurde nicht gefunden. Installiere den PostgreSQL-Client im ausfuehrenden Container."
            ) from exc

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "Unbekannter Fehler").strip()
            raise DatabaseBackupError(f"{command[0]} fehlgeschlagen: {error_text}")
        return result

    def create_dump(self, output_path: Path, table_names: Iterable[str] | None = None) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_command(self.build_dump_command(output_path, table_names))
        if not output_path.is_file():
            raise DatabaseBackupError("pg_dump wurde erfolgreich beendet, aber die Sicherungsdatei fehlt.")
        return output_path

    def restore_dump(self, backup_path: Path, table_names: Iterable[str] | None = None) -> None:
        if not backup_path.is_file():
            raise DatabaseBackupError(f"Backup-Datei nicht gefunden: {backup_path}")
        connections.close_all()
        self._run_command(self.build_restore_command(backup_path, table_names))

    def dump_table_names(self, backup_path: Path) -> list[str]:
        if not backup_path.is_file():
            raise DatabaseBackupError(f"Backup-Datei nicht gefunden: {backup_path}")
        result = self._run_command(["pg_restore", "--list", str(backup_path)], include_password=False)
        return self.parse_dump_table_names(result.stdout)

    def parse_dump_table_names(self, catalog: str) -> list[str]:
        table_names: set[str] = set()
        schema_name = self.schema_name()
        for raw_line in catalog.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            try:
                table_index = parts.index("TABLE")
            except ValueError:
                continue
            is_table_data = len(parts) > table_index + 1 and parts[table_index + 1] == "DATA"
            schema_index = table_index + (2 if is_table_data else 1)
            name_index = schema_index + 1
            if len(parts) <= name_index or parts[schema_index] != schema_name:
                continue
            table_name = parts[name_index]
            if self._IDENTIFIER_RE.fullmatch(table_name):
                table_names.add(table_name)
        return sorted(table_names)

    def restorable_table_names(self, backup: DatabaseBackup) -> list[str]:
        selected_tables = self.validate_table_names(backup.table_names)
        if selected_tables:
            return selected_tables
        return self.dump_table_names(self.backup_path(backup))

    def run_backup(self, backup_id: int) -> DatabaseBackup:
        backup = self.get(pk=backup_id)
        if backup.status != DatabaseBackup.Status.QUEUED:
            raise DatabaseBackupError("Der Backup-Auftrag ist nicht mehr in der Warteschlange.")

        backup.status = DatabaseBackup.Status.RUNNING
        backup.started_at = timezone.now()
        backup.completed_at = None
        backup.error_message = ""
        backup.save(update_fields=("status", "started_at", "completed_at", "error_message", "updated_at"))

        output_path: Path | None = None
        try:
            output_path = self.build_backup_path(backup)
            self.create_dump(output_path, backup.table_names)
            file_size_bytes = output_path.stat().st_size
        except Exception as exc:
            if output_path is not None:
                output_path.unlink(missing_ok=True)
            backup.status = DatabaseBackup.Status.FAILED
            backup.error_message = str(exc)
            backup.completed_at = timezone.now()
            backup.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise

        assert output_path is not None
        backup.status = DatabaseBackup.Status.SUCCEEDED
        backup.file_name = output_path.name
        backup.file_size_bytes = file_size_bytes
        backup.completed_at = timezone.now()
        backup.save(
            update_fields=(
                "status",
                "file_name",
                "file_size_bytes",
                "completed_at",
                "updated_at",
            )
        )
        return backup

    def request_restore(self, backup: DatabaseBackup, *, table_names: Iterable[str] | None, requested_by=None) -> None:
        if backup.status != DatabaseBackup.Status.SUCCEEDED:
            raise DatabaseBackupError("Nur erfolgreich erstellte Backups koennen wiederhergestellt werden.")
        if not self.backup_path(backup).is_file():
            raise DatabaseBackupError("Die Sicherungsdatei ist nicht mehr vorhanden.")

        selected_tables = self.validate_table_names(table_names)
        available_tables = set(self.restorable_table_names(backup))
        unknown_tables = sorted(set(selected_tables) - available_tables)
        if unknown_tables:
            raise DatabaseBackupError(
                f"Diese Tabellen sind nicht im Backup enthalten: {', '.join(unknown_tables)}"
            )

        backup.restore_status = DatabaseBackup.RestoreStatus.QUEUED
        backup.restore_table_names = selected_tables
        backup.restore_requested_by = requested_by
        backup.restore_started_at = None
        backup.restore_completed_at = None
        backup.restore_error_message = ""
        backup.save(
            update_fields=(
                "restore_status",
                "restore_table_names",
                "restore_requested_by",
                "restore_started_at",
                "restore_completed_at",
                "restore_error_message",
                "updated_at",
            )
        )

    def run_restore(self, backup_id: int) -> DatabaseBackup:
        backup = self.get(pk=backup_id)
        if backup.restore_status != DatabaseBackup.RestoreStatus.QUEUED:
            raise DatabaseBackupError("Der Wiederherstellungsauftrag ist nicht mehr in der Warteschlange.")

        backup.restore_status = DatabaseBackup.RestoreStatus.RUNNING
        backup.restore_started_at = timezone.now()
        backup.restore_completed_at = None
        backup.restore_error_message = ""
        backup.save(
            update_fields=(
                "restore_status",
                "restore_started_at",
                "restore_completed_at",
                "restore_error_message",
                "updated_at",
            )
        )

        try:
            self.restore_dump(self.backup_path(backup), backup.restore_table_names)
        except Exception as exc:
            backup = self.get(pk=backup_id)
            backup.restore_status = DatabaseBackup.RestoreStatus.FAILED
            backup.restore_error_message = str(exc)
            backup.restore_completed_at = timezone.now()
            backup.save(
                update_fields=(
                    "restore_status",
                    "restore_error_message",
                    "restore_completed_at",
                    "updated_at",
                )
            )
            raise

        backup = self.get(pk=backup_id)
        backup.restore_status = DatabaseBackup.RestoreStatus.SUCCEEDED
        backup.restore_completed_at = timezone.now()
        backup.restore_error_message = ""
        backup.save(
            update_fields=(
                "restore_status",
                "restore_completed_at",
                "restore_error_message",
                "updated_at",
            )
        )
        return backup

    def list_backup_files(self, *, directory: str | Path | None = None) -> list[Path]:
        return sorted(
            self.backup_directory(directory).glob(f"{self.backup_file_prefix}*.dump"),
            key=lambda path: path.stat().st_mtime,
        )

    def prune_backup_files(self, keep: int, *, directory: str | Path | None = None) -> list[Path]:
        if keep <= 0:
            return []
        deleted: list[Path] = []
        for path in self.list_backup_files(directory=directory)[:-keep]:
            path.unlink()
            deleted.append(path)
        return deleted
