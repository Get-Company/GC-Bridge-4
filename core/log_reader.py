from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings

from core.logging import cleanup_old_log_files, get_log_directories, get_log_retention_days


def get_allowed_log_files() -> list[Path]:
    cleanup_old_log_files()
    configured = [Path(item) for item in getattr(settings, "ADMIN_LOG_READER_FILES", []) if str(item).strip()]
    cutoff = datetime.now() - timedelta(days=get_log_retention_days())
    discovered: list[Path] = []
    for logs_dir in get_log_directories():
        if logs_dir.exists():
            for path in sorted(logs_dir.rglob("*.log*")):
                if not path.is_file():
                    continue
                try:
                    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
                except OSError:
                    continue
                if modified_at < cutoff:
                    continue
                discovered.append(path)

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in [*configured, *discovered]:
        if path.exists() and path.is_file():
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified_at < cutoff:
                continue
        normalized = str(path).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(Path(normalized))
    return unique_paths


def tail_log_file(path: Path, line_count: int = 50) -> list[str]:
    max_lines = max(1, min(int(line_count), 500))
    if not path.exists() or not path.is_file():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in deque(handle, maxlen=max_lines)]
