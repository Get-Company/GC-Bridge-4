from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from core.services import DatabaseBackupError, DatabaseBackupService
from core.tasks import create_database_backup, restore_database_backup


class DatabaseBackupServiceTest(SimpleTestCase):
    def setUp(self) -> None:
        self.service = DatabaseBackupService()

    def test_validate_table_names_deduplicates_valid_names(self):
        table_names = self.service.validate_table_names(
            ["products_product", "orders_order", "products_product"]
        )

        self.assertEqual(table_names, ["products_product", "orders_order"])

    def test_validate_table_names_rejects_unsafe_identifiers(self):
        with self.assertRaises(DatabaseBackupError):
            self.service.validate_table_names(["products_product; DROP TABLE auth_user"])

    def test_dump_command_limits_backup_to_selected_tables(self):
        command = self.service.build_dump_command(
            settings.BASE_DIR / "tmp" / "selected.dump",
            ["products_product", "orders_order"],
        )

        self.assertIn("--format=custom", command)
        self.assertIn("--table=public.products_product", command)
        self.assertIn("--table=public.orders_order", command)

    def test_restore_command_fails_fast_and_limits_selected_tables(self):
        command = self.service.build_restore_command(
            settings.BASE_DIR / "tmp" / "selected.dump",
            ["products_product"],
        )

        self.assertIn("--clean", command)
        self.assertIn("--exit-on-error", command)
        self.assertIn("--table=public.products_product", command)

    def test_parse_dump_table_names_uses_only_configured_schema(self):
        catalog = """
; Archive created at 2026-07-13 12:00:00 CEST
123; 1259 16384 TABLE public products_product app
124; 0 16384 TABLE DATA public products_product app
125; 1259 16385 TABLE other_schema ignored_table app
"""

        self.assertEqual(self.service.parse_dump_table_names(catalog), ["products_product"])


class DatabaseBackupTaskTest(SimpleTestCase):
    @patch("core.tasks.DatabaseBackupService")
    def test_create_task_runs_existing_backup_request(self, service_class):
        service = service_class.return_value
        service.run_backup.return_value = SimpleNamespace(
            pk=17,
            status="succeeded",
            file_name="gc_bridge_20260713_120000_17.dump",
        )

        result = create_database_backup.run(17)

        service.run_backup.assert_called_once_with(17)
        self.assertEqual(result["backup_id"], 17)
        self.assertEqual(result["status"], "succeeded")

    @patch("core.tasks.DatabaseBackupService")
    def test_create_task_creates_full_backup_when_no_request_is_given(self, service_class):
        service = service_class.return_value
        service.create_backup_request.return_value = SimpleNamespace(pk=23)
        service.run_backup.return_value = SimpleNamespace(
            pk=23,
            status="succeeded",
            file_name="gc_bridge_20260713_120000_23.dump",
        )

        result = create_database_backup.run()

        service.create_backup_request.assert_called_once_with(table_names=None, label="")
        service.run_backup.assert_called_once_with(23)
        self.assertEqual(result["backup_id"], 23)

    @patch("core.tasks.DatabaseBackupService")
    def test_restore_task_runs_requested_restore(self, service_class):
        service_class.return_value.run_restore.return_value = SimpleNamespace(pk=31, restore_status="succeeded")

        result = restore_database_backup.run(31)

        service_class.return_value.run_restore.assert_called_once_with(31)
        self.assertEqual(result, {"backup_id": 31, "restore_status": "succeeded"})
