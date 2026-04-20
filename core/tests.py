import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from core.logging import build_managed_log_path, cleanup_old_log_files
from core.log_reader import get_allowed_log_files, tail_log_file
from core.services import CommandRuntimeService


class ManagedLoggingTest(SimpleTestCase):
    def test_build_managed_log_path_uses_retention_directory(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            logs_root = base_dir / "tmp" / "logs"
            with override_settings(BASE_DIR=base_dir, LOGS_ROOT=logs_root):
                path = build_managed_log_path(
                    "deploy",
                    category="monthly",
                    now=datetime(2026, 3, 24, 15, 30),
                )

            self.assertEqual(path, logs_root / "monthly" / "deploy" / "deploy.2026-03-24.log")


class LogReaderUtilsTest(SimpleTestCase):
    def test_tail_log_file_returns_last_lines(self):
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "service.log"
            log_path.write_text("1\n2\n3\n4\n5\n", encoding="utf-8")
            lines = tail_log_file(log_path, 3)
            self.assertEqual(lines, ["3", "4", "5"])

    def test_get_allowed_log_files_includes_configured_and_discovered(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            logs_dir = base_dir / "logs"
            managed_logs_dir = base_dir / "tmp" / "logs" / "weekly" / "shopware"
            logs_dir.mkdir(parents=True, exist_ok=True)
            managed_logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "service_a.log").write_text("a\n", encoding="utf-8")
            (logs_dir / "service_b.log").write_text("b\n", encoding="utf-8")
            (managed_logs_dir / "shopware.2026-03-24.log").write_text("c\n", encoding="utf-8")

            configured = str(base_dir / "custom.log")
            with override_settings(
                BASE_DIR=base_dir,
                LOGS_ROOT=base_dir / "tmp" / "logs",
                ADMIN_LOG_READER_FILES=[configured],
            ):
                files = get_allowed_log_files()

            file_strings = {str(path) for path in files}
            self.assertIn(configured, file_strings)
            self.assertIn(str(logs_dir / "service_a.log"), file_strings)
            self.assertIn(str(logs_dir / "service_b.log"), file_strings)
            self.assertIn(str(managed_logs_dir / "shopware.2026-03-24.log"), file_strings)

    def test_get_allowed_log_files_excludes_and_deletes_logs_older_than_one_week(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            logs_dir = base_dir / "logs"
            managed_logs_dir = base_dir / "tmp" / "logs" / "weekly" / "shopware"
            logs_dir.mkdir(parents=True, exist_ok=True)
            managed_logs_dir.mkdir(parents=True, exist_ok=True)

            stale_legacy = logs_dir / "service_old.log"
            stale_managed = managed_logs_dir / "shopware.2026-03-01.log"
            fresh_log = managed_logs_dir / "shopware.2026-03-24.log"
            stale_legacy.write_text("old\n", encoding="utf-8")
            stale_managed.write_text("old\n", encoding="utf-8")
            fresh_log.write_text("new\n", encoding="utf-8")

            stale_timestamp = (datetime.now().timestamp() - (9 * 24 * 60 * 60))
            os.utime(stale_legacy, (stale_timestamp, stale_timestamp))
            os.utime(stale_managed, (stale_timestamp, stale_timestamp))

            with override_settings(
                BASE_DIR=base_dir,
                LOGS_ROOT=base_dir / "tmp" / "logs",
                SYSTEM_LOG_RETENTION_DAYS=7,
            ):
                files = get_allowed_log_files()

            file_strings = {str(path) for path in files}
            self.assertNotIn(str(stale_legacy), file_strings)
            self.assertNotIn(str(stale_managed), file_strings)
            self.assertIn(str(fresh_log), file_strings)
            self.assertFalse(stale_legacy.exists())
            self.assertFalse(stale_managed.exists())
            self.assertTrue(fresh_log.exists())

    def test_cleanup_old_log_files_returns_deleted_count(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            managed_logs_dir = base_dir / "tmp" / "logs" / "weekly" / "products"
            managed_logs_dir.mkdir(parents=True, exist_ok=True)
            stale_log = managed_logs_dir / "products.2026-03-01.log"
            fresh_log = managed_logs_dir / "products.2026-03-24.log"
            stale_log.write_text("old\n", encoding="utf-8")
            fresh_log.write_text("new\n", encoding="utf-8")

            stale_timestamp = (datetime.now().timestamp() - (10 * 24 * 60 * 60))
            os.utime(stale_log, (stale_timestamp, stale_timestamp))

            with override_settings(
                BASE_DIR=base_dir,
                LOGS_ROOT=base_dir / "tmp" / "logs",
                SYSTEM_LOG_RETENTION_DAYS=7,
            ):
                deleted_count = cleanup_old_log_files()

            self.assertEqual(deleted_count, 1)
            self.assertFalse(stale_log.exists())
            self.assertTrue(fresh_log.exists())


class CommandRuntimeServiceTest(SimpleTestCase):
    def test_start_update_close_lifecycle(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            with override_settings(BASE_DIR=base_dir):
                service = CommandRuntimeService()
                handle = service.start(
                    command_name="scheduled_product_sync",
                    argv=["manage.py", "scheduled_product_sync", "--limit", "5"],
                    metadata={"stage": "1/4"},
                )

                entries = service.list_runs()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["command_name"], "scheduled_product_sync")
                self.assertEqual(entries[0]["metadata"].get("stage"), "1/4")

                handle.update(stage="2/4")
                entries = service.list_runs()
                self.assertEqual(entries[0]["metadata"].get("stage"), "2/4")

                handle.close()
                self.assertEqual(service.list_runs(), [])
