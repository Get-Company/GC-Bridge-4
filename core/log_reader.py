from __future__ import annotations

from collections import deque
from pathlib import Path

from django.conf import settings


def get_allowed_log_files() -> list[Path]:
    configured = [Path(item) for item in getattr(settings, "ADMIN_LOG_READER_FILES", []) if str(item).strip()]
    defaults = [
        settings.BASE_DIR / "logs" / "scheduled_product_sync.log",
        settings.BASE_DIR / "logs" / "django.log",
    ]
    discovered: list[Path] = []
    logs_dir = settings.BASE_DIR / "logs"
    if logs_dir.exists():
        discovered = sorted(path for path in logs_dir.glob("*.log") if path.is_file())

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in [*configured, *defaults, *discovered]:
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

