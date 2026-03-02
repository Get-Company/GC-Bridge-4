from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from core.log_reader import get_allowed_log_files, tail_log_file


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
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "service_a.log").write_text("a\n", encoding="utf-8")
            (logs_dir / "service_b.log").write_text("b\n", encoding="utf-8")

            configured = str(base_dir / "custom.log")
            with override_settings(BASE_DIR=base_dir, ADMIN_LOG_READER_FILES=[configured]):
                files = get_allowed_log_files()

            file_strings = {str(path) for path in files}
            self.assertIn(configured, file_strings)
            self.assertIn(str(logs_dir / "service_a.log"), file_strings)
            self.assertIn(str(logs_dir / "service_b.log"), file_strings)
