from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from ai.management.commands.import_legacy_ai_rewrites import Command as ImportLegacyAIRewritesCommand
from ai.services.provider import AIProviderService


class AIProviderServiceTest(SimpleTestCase):
    def test_extract_message_content_supports_string_content(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": " Hallo Welt ",
                    }
                }
            ]
        }

        result = AIProviderService._extract_message_content(payload)

        self.assertEqual(result, "Hallo Welt")

    def test_extract_message_content_supports_content_parts(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Teil 1 "},
                            {"type": "text", "text": "Teil 2"},
                        ]
                    }
                }
            ]
        }

        result = AIProviderService._extract_message_content(payload)

        self.assertEqual(result, "Teil 1 Teil 2")


class ImportLegacyAIRewritesCommandTest(SimpleTestCase):
    def test_map_field_name_maps_legacy_description_fields(self):
        command = ImportLegacyAIRewritesCommand()

        self.assertEqual(command._map_field_name("description"), "description_de")
        self.assertEqual(command._map_field_name("description_short"), "description_short_de")

    def test_normalize_result_text_unwraps_json_string(self):
        result = ImportLegacyAIRewritesCommand._normalize_result_text('"Hallo"')

        self.assertEqual(result, "Hallo")

    def test_map_status_marks_matching_legacy_value_as_applied(self):
        command = ImportLegacyAIRewritesCommand()

        status = command._map_status(
            legacy_status="FOR_APPROVAL",
            legacy_target_value="<p>Text</p>",
            result_text="<p>Text</p>",
        )

        self.assertEqual(status, "applied")

    def test_resolve_sqlite_path_builds_from_dump_when_missing(self):
        command = ImportLegacyAIRewritesCommand()

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dump_path = temp_path / "database.sql"
            sqlite_path = temp_path / "legacy.sqlite3"
            dump_path.write_text("-- dump", encoding="utf-8")

            with patch("ai.management.commands.import_legacy_ai_rewrites.call_command") as mocked_call_command:
                def _create_sqlite(*args, **kwargs):
                    sqlite_path.write_text("", encoding="utf-8")

                mocked_call_command.side_effect = _create_sqlite

                resolved_path = command._resolve_sqlite_path(
                    sqlite_path_value=str(sqlite_path),
                    dump_path_value=str(dump_path),
                    rebuild_sqlite=False,
                )

            self.assertEqual(resolved_path, sqlite_path.resolve())
            mocked_call_command.assert_called_once_with(
                "legacy_dump_to_sqlite",
                str(dump_path.resolve()),
                str(sqlite_path.resolve()),
                overwrite=True,
            )

    def test_resolve_sqlite_path_raises_when_neither_dump_nor_sqlite_exists(self):
        command = ImportLegacyAIRewritesCommand()

        with TemporaryDirectory() as temp_dir:
            missing_sqlite = Path(temp_dir) / "missing.sqlite3"

            with self.assertRaises(CommandError):
                command._resolve_sqlite_path(
                    sqlite_path_value=str(missing_sqlite),
                    dump_path_value="",
                    rebuild_sqlite=False,
                )
