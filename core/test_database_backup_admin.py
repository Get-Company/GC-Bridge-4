from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import DatabaseBackup
from core.services import DatabaseBackupService


class DatabaseBackupAdminChangeViewTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.superuser = get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "password"
        )

    def setUp(self) -> None:
        self.client.force_login(self.superuser)

    def test_change_view_renders_for_full_backup(self):
        backup = DatabaseBackup.objects.create(
            label="Voll-Backup",
            status=DatabaseBackup.Status.SUCCEEDED,
            file_name="gc_bridge_full.dump",
            file_size_bytes=2048,
            table_names=[],
        )

        response = self.client.get(
            reverse("admin:core_databasebackup_change", args=(backup.pk,))
        )

        self.assertEqual(response.status_code, 200)

    def _restore_url(self, backup: DatabaseBackup) -> str:
        return reverse(
            "admin:core_databasebackup_restore_database_backup_detail", args=(backup.pk,)
        )

    def test_restore_view_blocks_on_dependency_gap_without_acknowledgement(self):
        backup = DatabaseBackup.objects.create(
            label="Teil-Restore",
            status=DatabaseBackup.Status.SUCCEEDED,
            file_name="gc_bridge_partial.dump",
            file_size_bytes=1024,
            table_names=["auth_user", "django_admin_log"],
        )

        with patch.object(DatabaseBackupService, "request_restore") as request_restore:
            response = self.client.post(
                self._restore_url(backup),
                data={
                    "table_names": ["auth_user"],
                    "confirm_restore": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        request_restore.assert_not_called()
        self.assertContains(response, "django_admin_log")

    def test_restore_view_proceeds_when_dependencies_acknowledged(self):
        backup = DatabaseBackup.objects.create(
            label="Teil-Restore",
            status=DatabaseBackup.Status.SUCCEEDED,
            file_name="gc_bridge_partial.dump",
            file_size_bytes=1024,
            table_names=["auth_user", "django_admin_log"],
        )

        with patch.object(DatabaseBackupService, "request_restore") as request_restore:
            response = self.client.post(
                self._restore_url(backup),
                data={
                    "table_names": ["auth_user"],
                    "acknowledge_dependencies": "on",
                    "confirm_restore": "on",
                },
            )

        self.assertEqual(response.status_code, 302)
        request_restore.assert_called_once()

    def test_change_view_renders_for_table_scoped_backup(self):
        backup = DatabaseBackup.objects.create(
            label="Teil-Backup",
            status=DatabaseBackup.Status.SUCCEEDED,
            file_name="gc_bridge_partial.dump",
            file_size_bytes=1024,
            table_names=["products_product", "orders_order"],
        )

        response = self.client.get(
            reverse("admin:core_databasebackup_change", args=(backup.pk,))
        )

        self.assertEqual(response.status_code, 200)


class RestoreDependencyAnalysisTest(TestCase):
    def setUp(self) -> None:
        self.service = DatabaseBackupService()

    def test_flags_missing_prerequisite_tables(self):
        report = self.service.analyze_restore_dependencies(["django_admin_log"])

        prerequisite_names = {related.table for related in report.prerequisite_tables}
        self.assertIn("auth_user", prerequisite_names)
        self.assertIn("django_content_type", prerequisite_names)
        self.assertTrue(any("Voraussetzung" in problem for problem in report.problems))

    def test_flags_missing_dependent_tables(self):
        report = self.service.analyze_restore_dependencies(["auth_user"])

        dependent_names = {related.table for related in report.dependent_tables}
        self.assertIn("django_admin_log", dependent_names)
        self.assertTrue(any("Abhaengigkeit" in problem for problem in report.problems))

    def test_no_warnings_when_all_related_tables_included(self):
        report = self.service.analyze_restore_dependencies(
            ["auth_group", "auth_group_permissions", "auth_permission", "django_content_type"]
        )

        # auth_group_permissions -> auth_group + auth_permission (beide gewaehlt);
        # auth_permission -> django_content_type (gewaehlt). Keine offenen Kanten.
        self.assertEqual(report.prerequisite_tables, [])
        self.assertFalse(any(r.table == "auth_group" for r in report.dependent_tables))

    def test_full_restore_without_selection_has_no_warnings(self):
        report = self.service.analyze_restore_dependencies([])

        self.assertFalse(report.has_warnings)
        self.assertEqual(report.problems, [])
