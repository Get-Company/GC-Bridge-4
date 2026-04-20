from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from django.conf import settings
from loguru import logger

DEFAULT_LOG_RETENTION = {
    "daily": "8 days",
    "weekly": "6 weeks",
    "monthly": "13 months",
}

PACKAGE_RETENTION = {
    "core": "weekly",
    "customer": "weekly",
    "orders": "weekly",
    "products": "weekly",
    "shopware": "weekly",
    "microtech": "monthly",
    "django": "weekly",
    "uvicorn": "daily",
}

LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}"
)
DEFAULT_SYSTEM_LOG_RETENTION_DAYS = 7

_CONFIGURE_LOCK = Lock()
_CONFIGURED = False


def _base_dir() -> Path:
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir:
        return Path(base_dir)
    return Path(__file__).resolve().parents[1]


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    return cleaned.strip("_") or "app"


def get_logs_root() -> Path:
    configured = getattr(settings, "LOGS_ROOT", "") or ""
    configured_path = Path(str(configured))
    if configured_path.is_absolute():
        return configured_path
    return _base_dir() / configured_path if str(configured_path).strip() else _base_dir() / "tmp" / "logs"


def get_log_retention_days() -> int:
    configured = getattr(settings, "SYSTEM_LOG_RETENTION_DAYS", DEFAULT_SYSTEM_LOG_RETENTION_DAYS)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return DEFAULT_SYSTEM_LOG_RETENTION_DAYS


def get_log_directories(*, include_legacy: bool = True) -> list[Path]:
    directories: list[Path] = []
    if include_legacy:
        directories.append(_base_dir() / "logs")
    directories.append(get_logs_root())

    unique: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        normalized = str(directory.resolve()) if directory.exists() else str(directory)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(directory)
    return unique


def cleanup_old_log_files(*, retention_days: int | None = None, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now()) - timedelta(days=retention_days or get_log_retention_days())
    deleted = 0

    for logs_dir in get_log_directories():
        if not logs_dir.exists():
            continue
        for path in logs_dir.rglob("*.log*"):
            if not path.is_file():
                continue
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified_at >= cutoff:
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError:
                continue

    return deleted


def get_retention(category: str) -> str:
    normalized = str(category or "").strip().lower()
    if normalized not in DEFAULT_LOG_RETENTION:
        raise ValueError(f"Unsupported log retention category: {category}")
    setting_name = f"LOG_RETENTION_{normalized.upper()}"
    configured = str(getattr(settings, setting_name, "") or "").strip()
    return configured or DEFAULT_LOG_RETENTION[normalized]


def build_managed_log_path(log_name: str, *, category: str = "weekly", now: datetime | None = None) -> Path:
    safe_name = _safe_name(log_name)
    date_stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    return get_logs_root() / category / safe_name / f"{safe_name}.{date_stamp}.log"


def build_managed_log_pattern(log_name: str, *, category: str = "weekly") -> Path:
    safe_name = _safe_name(log_name)
    return get_logs_root() / category / safe_name / f"{safe_name}.{{time:YYYY-MM-DD}}.log"


def add_managed_file_sink(
    *,
    log_name: str,
    category: str = "weekly",
    log_file: str | Path | None = None,
    level: str = "DEBUG",
    rotation: str = "00:00",
    enqueue: bool = False,
    backtrace: bool = True,
    diagnose: bool = False,
    log_format: str = LOG_FORMAT,
) -> tuple[int, Path]:
    cleanup_old_log_files()
    path = Path(log_file) if log_file else build_managed_log_path(log_name, category=category)
    path.parent.mkdir(parents=True, exist_ok=True)
    sink_id = logger.add(
        str(path),
        level=level,
        enqueue=enqueue,
        backtrace=backtrace,
        diagnose=diagnose,
        rotation=rotation,
        retention=get_retention(category),
        encoding="utf-8",
        format=log_format,
    )
    return sink_id, path


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        depth = 2
        frame = logging.currentframe()
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(python_logger_name=record.name).opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def _record_matches_package(record: dict[str, Any], package_name: str) -> bool:
    candidates = {
        str(record.get("name") or "").strip(),
        str(record.get("extra", {}).get("python_logger_name") or "").strip(),
    }
    return any(
        candidate == package_name or candidate.startswith(f"{package_name}.")
        for candidate in candidates
        if candidate
    )


def _configure_stdlib_logging() -> None:
    intercept_handler = InterceptHandler()
    logging.basicConfig(handlers=[intercept_handler], level=0, force=True)
    for logger_name in ("django", "uvicorn", "uvicorn.error", "uvicorn.access"):
        stdlib_logger = logging.getLogger(logger_name)
        stdlib_logger.handlers = [intercept_handler]
        stdlib_logger.propagate = False


def configure_logging() -> None:
    global _CONFIGURED

    with _CONFIGURE_LOCK:
        if _CONFIGURED:
            return

        logs_root = get_logs_root()
        logs_root.mkdir(parents=True, exist_ok=True)
        cleanup_old_log_files()

        logger.remove()
        logger.add(
            sys.stderr,
            level="DEBUG" if getattr(settings, "DEBUG", False) else "INFO",
            enqueue=False,
            backtrace=False,
            diagnose=False,
            format=LOG_FORMAT,
        )

        for package_name, category in PACKAGE_RETENTION.items():
            log_path = build_managed_log_pattern(package_name, category=category)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logger.add(
                str(log_path),
                level="DEBUG",
                enqueue=False,
                backtrace=True,
                diagnose=False,
                rotation="00:00",
                retention=get_retention(category),
                encoding="utf-8",
                format=LOG_FORMAT,
                filter=lambda record, prefix=package_name: _record_matches_package(record, prefix),
            )

        error_path = build_managed_log_pattern("errors", category="monthly")
        error_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(error_path),
            level="ERROR",
            enqueue=False,
            backtrace=True,
            diagnose=False,
            rotation="00:00",
            retention=get_retention("monthly"),
            encoding="utf-8",
            format=LOG_FORMAT,
        )

        _configure_stdlib_logging()
        _CONFIGURED = True
